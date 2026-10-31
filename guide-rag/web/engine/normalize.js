// Port of guide_rag/question/normalize.py: folding, tokens, abbreviations, weak words, spell
// correction against the corpus vocabulary, language vote. Deterministic and model-free; the
// original wording is never lost.

import { isDigits, pyCompare, sortedBy, sortedStrings } from "./_py.js";
import {
  DE_STOP_WORDS,
  EN_STOP_WORDS,
  FR_STOP_WORDS,
  PRONOUN_PHRASES,
  PRONOUNS,
  EMPTY_CONTENT_WORDS,
  is_stop_word,
  stem,
} from "./stopwords.js";

// A word is letters and digits; apostrophes and hyphens split ("l'assurance" -> "l", "assurance").
const _WORD_RE = /[\p{L}\p{N}]+/gu;
const _FOLD_MAP = { "œ": "oe", "æ": "ae", "ß": "ss", "Œ": "oe", "Æ": "ae" };

/** Lowercase and strip accents; ligatures are spelled out. For matching only. */
export function fold(text) {
  const lowered = text.toLowerCase().replace(/[œæßŒÆ]/g, (ch) => _FOLD_MAP[ch]);
  return lowered.normalize("NFKD").replace(/\p{M}/gu, "");
}

/** Lowercase word tokens with their accents; apostrophes, hyphens and punctuation split. */
export function tokenize(text) {
  return Array.from(text.replace(/’/g, "'").matchAll(_WORD_RE), (m) => m[0].toLowerCase());
}

export function fold_tokens(text) {
  return tokenize(text).map(fold);
}

/** The tokens that can carry the subject: not a stop word, not a pronoun, not "chose". */
export function content_tokens(folded_tokens) {
  // Digits of any length stay: "112", "classe 1" and "L-1234" are subjects too.
  return Array.from(folded_tokens).filter(
    (t) => !is_stop_word(t) && !PRONOUNS.has(t) && !EMPTY_CONTENT_WORDS.has(t) && (t.length > 1 || isDigits(t)),
  );
}

// ----------------------------------------------------------------------------- abbreviations

export class Abbreviation {
  constructor(abbreviation, expansion, language = null, note = null) {
    this.abbreviation = abbreviation;
    this.expansion = expansion;
    this.language = language;
    this.note = note;
  }
}

/** The table of `dictionary/abbreviations.yaml`, keyed by the folded short form. */
export class Abbreviations {
  constructor(entries) {
    this._by_key = new Map();
    for (const entry of entries) this._by_key.set(fold(entry.abbreviation), entry);
  }

  /** From the `abbreviations` rows of web/data/dictionary.json (the YAML, exported by build_data.py). */
  static load(rows) {
    const entries = (rows || []).map(
      (row) => new Abbreviation(String(row.abbreviation), String(row.expansion), row.language ?? null, row.note ?? null),
    );
    return new Abbreviations(entries);
  }

  get length() {
    return this._by_key.size;
  }

  has(token) {
    return this._by_key.has(fold(token));
  }

  get(token) {
    return this._by_key.get(fold(token)) ?? null;
  }

  items() {
    return sortedBy(Array.from(this._by_key.entries()), ([k]) => [k]);
  }
}

// ----------------------------------------------------------------------------- weak words

/**
 * The words of `dictionary/weak_words.yaml`: kept as keywords, never trusted to pick a topic.
 * Matched by stem so "documents" and "document" are one entry.
 */
export class WeakWords {
  constructor(words_by_language) {
    this._stems = new Map();
    for (const [lang, ws] of Object.entries(words_by_language || {})) {
      this._stems.set(lang, new Set(Array.from(ws || [], (w) => stem(fold(String(w))))));
    }
    this._all = new Set();
    for (const s of this._stems.values()) for (const w of s) this._all.add(w);
  }

  /** From the `weak_words` block of web/data/dictionary.json ({lang: [word, ...]}). */
  static load(raw) {
    const out = {};
    for (const [lang, ws] of Object.entries(raw || {})) out[lang] = Array.from(ws || []);
    return new WeakWords(out);
  }

  get length() {
    return this._all.size;
  }

  has(token) {
    return this._all.has(stem(fold(token)));
  }

  languages() {
    return sortedStrings(this._stems.keys());
  }
}

// ----------------------------------------------------------------------------- vocabulary

/** Optimal string alignment distance with an early exit above `max_distance`. */
export function damerau_levenshtein(a, b, max_distance = 2) {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > max_distance) return max_distance + 1;
  let previous2 = null;
  let previous = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const ca = a[i - 1];
    const current = new Array(b.length + 1).fill(0);
    current[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cb = b[j - 1];
      const cost = ca === cb ? 0 : 1;
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
      if (previous2 !== null && i > 1 && j > 1 && ca === b[j - 2] && a[i - 2] === cb) {
        current[j] = Math.min(current[j], previous2[j - 2] + 1);
      }
    }
    if (Math.min(...current) > max_distance) return max_distance + 1;
    previous2 = previous;
    previous = current;
  }
  return previous[b.length];
}

export class Correction {
  constructor(original, corrected, display, distance, frequency) {
    this.original = original; // the folded token the reader typed
    this.corrected = corrected; // the folded corpus term
    this.display = display; // the corpus term as the corpus spells it (accents kept)
    this.distance = distance;
    this.frequency = frequency;
  }
}

/**
 * The corpus vocabulary with a SymSpell-like deletes index for spell correction. Built from
 * `line_df.text` at runtime, never from a model. A token the corpus knows is never corrected; a
 * token nothing is close to is kept as typed.
 */
export class Vocabulary {
  constructor(counts, display = null, { known_terms = [], max_edit_distance = 2, prefix_length = 7, min_term_length = 3 } = {}) {
    this.max_edit_distance = max_edit_distance;
    this.prefix_length = prefix_length;
    this.min_term_length = min_term_length;
    this._counts = new Map();
    for (const [t, c] of counts instanceof Map ? counts : Object.entries(counts)) if (t.length >= 1) this._counts.set(t, c);
    this._display = new Map(display instanceof Map ? display : Object.entries(display || {}));
    // Words the dictionary knows are never typos, even when the corpus does not use them.
    for (const term of known_terms) {
      for (const token of tokenize(term)) {
        const folded = fold(token);
        if (!this._counts.has(folded)) this._counts.set(folded, 0);
        if (!this._display.has(folded)) this._display.set(folded, token);
      }
    }
    this._deletes = new Map();
    for (const term of sortedStrings(this._counts.keys())) {
      if (term.length < min_term_length) continue;
      for (const deleted of this._deletes_of(term.slice(0, prefix_length))) {
        let bucket = this._deletes.get(deleted);
        if (!bucket) this._deletes.set(deleted, (bucket = []));
        bucket.push(term);
      }
    }
  }

  // -- construction

  static from_texts(texts, options = {}) {
    const counts = new Map();
    const surface = new Map();
    for (const text of texts) {
      if (typeof text !== "string") continue;
      for (const token of tokenize(text)) {
        const folded = fold(token);
        counts.set(folded, (counts.get(folded) || 0) + 1);
        let forms = surface.get(folded);
        if (!forms) surface.set(folded, (forms = new Map()));
        forms.set(token, (forms.get(token) || 0) + 1);
      }
    }
    const display = new Map();
    for (const [f, forms] of surface) {
      const best = sortedBy(Array.from(forms.entries()), ([tok, n]) => [-n, tok])[0][0];
      display.set(f, best);
    }
    return new Vocabulary(counts, display, options);
  }

  /** The vocabulary of the citation units (line_df as an array of records); empty gives empty. */
  static from_line_df(line_df, text_column = "text", options = {}) {
    if (!line_df || line_df.length === 0 || !(text_column in line_df[0])) return new Vocabulary(new Map(), new Map(), options);
    return Vocabulary.from_texts(line_df.map((r) => r[text_column]), options);
  }

  // -- queries

  get length() {
    return this._counts.size;
  }

  has(token) {
    return this._counts.has(fold(token));
  }

  frequency(token) {
    return this._counts.get(fold(token)) ?? 0;
  }

  display(folded_term) {
    return this._display.get(folded_term) ?? folded_term;
  }

  /**
   * The closest corpus term within the edit distance, or null to keep the token. A known token is
   * never corrected; tokens shorter than five letters or with digits are never corrected; tokens
   * of six letters or fewer tolerate one edit only; a correction never lands on a stop word, only
   * on a term the corpus uses at least once, and keeps the first letter.
   */
  lookup(token) {
    const folded = fold(token);
    if (this._counts.has(folded)) return null;
    if (folded.length < 5 || /\p{Nd}/u.test(folded)) return null;
    const allowed = folded.length <= 6 ? 1 : this.max_edit_distance;
    const candidates = new Set();
    for (const deleted of this._deletes_of(folded.slice(0, this.prefix_length))) {
      for (const term of this._deletes.get(deleted) || []) candidates.add(term);
    }
    let best = null;
    for (const term of candidates) {
      if (term.length < 4 || is_stop_word(term) || this._counts.get(term) < 1 || term[0] !== folded[0]) continue;
      const distance = damerau_levenshtein(folded, term, allowed);
      if (distance > allowed) continue;
      const key = [distance, -this._counts.get(term), term];
      if (best === null || compareKey(key, best) < 0) best = key;
    }
    if (best === null) return null;
    const [distance, neg_freq, term] = best;
    return new Correction(folded, term, this.display(term), distance, -neg_freq);
  }

  correct(token) {
    const found = this.lookup(token);
    return found ? found.display : token;
  }

  // -- internals

  /** All strings within `max_edit_distance` deletions of `term`, the term included. */
  _deletes_of(term) {
    const results = new Set([term]);
    let frontier = new Set([term]);
    for (let n = 0; n < this.max_edit_distance; n++) {
      const next_frontier = new Set();
      for (const word of frontier) {
        if (word.length <= 1) continue;
        for (let i = 0; i < word.length; i++) {
          const shorter = word.slice(0, i) + word.slice(i + 1);
          if (!results.has(shorter)) {
            results.add(shorter);
            next_frontier.add(shorter);
          }
        }
      }
      frontier = next_frontier;
    }
    return results;
  }
}

function compareKey(a, b) {
  for (let i = 0; i < a.length; i++) {
    const c = pyCompare(a[i], b[i]);
    if (c !== 0) return c;
  }
  return 0;
}

// ----------------------------------------------------------------------------- language

/** Stop-word vote; `extra_votes` (the languages of matched dictionary variants) break ties. */
export function detect_language(folded_tokens, extra_votes = null) {
  const votes = { fr: 0, en: 0, de: 0 };
  for (const token of folded_tokens) {
    if (FR_STOP_WORDS.has(token)) votes.fr += 1;
    if (EN_STOP_WORDS.has(token)) votes.en += 1;
    if (DE_STOP_WORDS.has(token)) votes.de += 1;
  }
  let best = _winner(votes);
  if (best !== null) return best;
  if (extra_votes && Object.keys(extra_votes).length) {
    const merged = {};
    for (const lang of Object.keys(votes)) merged[lang] = (votes[lang] || 0) + (extra_votes[lang] || 0);
    best = _winner(merged);
    if (best !== null) return best;
  }
  return "unknown";
}

function _winner(votes) {
  const top = Math.max(...Object.values(votes));
  if (top === 0) return null;
  const leaders = Object.keys(votes).filter((lang) => votes[lang] === top);
  if (leaders.length === 1) return leaders[0];
  // A tie between languages would be a guess, so say unknown.
  return null;
}

// ----------------------------------------------------------------------------- the pipeline

export class NormalizedQuestion {
  constructor(fields) {
    this.original = fields.original;
    this.corrected = fields.corrected; // lowercase, abbreviations expanded, typos corrected, accents kept
    this.tokens = fields.tokens; // tokens of `corrected`, accents kept
    this.folded_tokens = fields.folded_tokens; // the same, accent-folded
    this.content = fields.content; // folded content tokens (no stop words, no pronouns)
    this.expansions = fields.expansions || []; // [abbreviation, expansion]
    this.corrections = fields.corrections || [];
    this.language = fields.language || "unknown";
    this.pronouns_seen = fields.pronouns_seen || [];
  }

  get folded() {
    return fold(this.corrected);
  }

  stems() {
    return this.content.map(stem);
  }
}

/**
 * Lowercase, expand abbreviations, correct typos against the corpus, tokenise, vote a language.
 * The abbreviation pass runs before the spell pass, so "RC" is never "corrected" to a corpus word.
 */
export function normalize_question(question, { vocabulary = null, abbreviations = null } = {}) {
  abbreviations = abbreviations || new Abbreviations([]);
  const lowered = question.trim().toLowerCase().replace(/’/g, "'");
  const expansions = [];
  const corrections = [];

  const replace = (token) => {
    const abbreviation = abbreviations.get(token);
    if (abbreviation !== null) {
      expansions.push([token, abbreviation.expansion]);
      return abbreviation.expansion;
    }
    const folded = fold(token);
    if (vocabulary !== null && !is_stop_word(folded) && !PRONOUNS.has(folded) && !EMPTY_CONTENT_WORDS.has(folded)) {
      const found = vocabulary.lookup(token);
      if (found !== null) {
        corrections.push(found);
        return found.display;
      }
    }
    return token;
  };

  const corrected = lowered.replace(_WORD_RE, replace);
  const tokens = tokenize(corrected);
  const folded_tokens = tokens.map(fold);
  const folded_text = fold(corrected);
  let pronouns_seen = PRONOUN_PHRASES.filter((p) => folded_text.includes(p));
  pronouns_seen = pronouns_seen.concat(folded_tokens.filter((t) => PRONOUNS.has(t)));
  const content = content_tokens(folded_tokens);
  return new NormalizedQuestion({
    original: question,
    corrected,
    tokens,
    folded_tokens,
    content,
    expansions,
    corrections,
    language: detect_language(folded_tokens),
    pronouns_seen,
  });
}
