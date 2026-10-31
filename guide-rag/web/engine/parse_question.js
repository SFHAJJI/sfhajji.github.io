// Port of guide_rag/question/parse_question.py (brick 2): the question becomes a `ParsedQuestion`
// row. Deterministic, model-free; every decision leaves a sentence in `parsing_notes`.

import { escapeRegex, isDigits, pyDictRepr, pyListRepr, pyRegex, pyRound, reSearch, sha1Hex, sortedBy, sortedStrings } from "./_py.js";
import { Dictionary } from "./dictionary.js";
import {
  Abbreviations,
  Vocabulary,
  WeakWords,
  content_tokens,
  damerau_levenshtein,
  detect_language,
  fold,
  fold_tokens,
  normalize_question,
} from "./normalize.js";
import { stem } from "./stopwords.js";

export const DICTIONARY_WEIGHT = 0.6; // SPEC §2: every variant of a matched concept
export const WEAK_WEIGHT = 0.3;

// ----------------------------------------------------------------------------- the model

export function Keyword({ text, weight, source, concept = null, is_regex = false, weak = false, in_corpus = true }) {
  return { text, weight, source, concept, is_regex, weak, in_corpus };
}

export function StructuralHints({ pages_hint = null, toc_section_hint = null, answer_context = "paragraph" } = {}) {
  return { pages_hint, toc_section_hint, answer_context };
}

export function ScopeFilters({ topic = null } = {}) {
  return { topic };
}

export function Decomposition({ pattern = "single", sub_questions = [] } = {}) {
  return { pattern, sub_questions };
}

export function ParsedQuestion(fields) {
  return {
    question_id: fields.question_id,
    original_question: fields.original_question,
    corrected_question: fields.corrected_question,
    language: fields.language,
    keywords: fields.keywords,
    answer_shape: fields.answer_shape,
    answer_type: fields.answer_type,
    structural_hints: fields.structural_hints,
    scope_filters: fields.scope_filters,
    decomposition: fields.decomposition,
    suggested_clarification: fields.suggested_clarification ?? null,
    ambiguity_reason: fields.ambiguity_reason ?? null,
    candidate_values: fields.candidate_values ?? [],
    proposed_default: fields.proposed_default ?? null,
    parsing_notes: fields.parsing_notes ?? [],
  };
}

export function needs_clarification(parsed) {
  return parsed.ambiguity_reason !== null && parsed.ambiguity_reason !== undefined;
}

export function concepts_of(parsed) {
  const seen = [];
  for (const k of parsed.keywords) if (k.concept && !seen.includes(k.concept)) seen.push(k.concept);
  return seen;
}

export function question_id_of(original) {
  return sha1Hex(original).slice(0, 16);
}

// ----------------------------------------------------------------------------- cue tables
// Cues are matched on the folded corrected question (lowercase, no accents), whole words.

export const LISTING_CUES = [
  // fr
  "quels", "quelles", "lesquels", "lesquelles", "liste", "lister", "listez", "enumerer", "enumere",
  "toutes les", "tous les", "les etapes", "etapes", "pieces a fournir", "documents necessaires",
  "documents a fournir", "quelles sont", "quels sont",
  // en
  "which", "what are", "list", "all the", "all of", "steps", "documents needed", "documents required",
  "what documents", "requirements",
  // de
  "welche", "welches", "liste", "alle", "schritte", "unterlagen", "dokumente",
];

export const BOOLEAN_FRAMES = [
  "est-ce que", "est ce que", "est-ce qu", "est ce qu", "dois-je", "dois je", "doit-on", "doit on",
  "puis-je", "puis je", "peut-on", "peut on", "faut-il", "faut il", "y a-t-il", "y a t il", "ai-je",
  "suis-je", "est-il", "est-elle", "est il", "est elle", "a-t-on", "peux-je",
  "can i", "could i", "do i", "does", "must i", "should i", "is it", "is the", "is there", "are there",
  "am i", "will i", "can we", "may i", "do we", "are the", "have i",
  "muss ich", "kann ich", "darf ich", "soll ich", "ist es", "gibt es", "brauche ich", "ist die",
  "ist der", "ist das", "mussen wir", "konnen wir",
];

export const DURATION_CUES = [
  "combien de temps", "duree", "delai", "delais", "validite", "valable", "pendant combien",
  "how long", "duration", "validity", "valid for", "how many days", "how many months", "how many years",
  "wie lange", "dauer", "gultig", "gultigkeit", "frist",
];
export const AMOUNT_CUES = [
  "combien", "coute", "coutent", "cout", "couts", "prix", "montant", "tarif", "tarifs", "frais", "euros",
  "euro", "€",
  "how much", "cost", "costs", "price", "fee", "fees", "amount",
  "wie viel", "wieviel", "wie hoch", "kostet", "kosten", "preis", "gebuhr", "gebuhren", "betrag", "betragt",
];
export const DATE_CUES = [
  "quand", "quelle date", "a partir de quand", "jusqu a quand", "echeance", "date limite", "date",
  "when", "deadline", "by when", "what date",
  "wann", "datum", "ab wann", "bis wann", "stichtag",
];
export const PHONE_CUES = [
  "telephone", "numero de telephone", "appeler", "tel", "hotline",
  "phone", "phone number", "call", "telephone number",
  "telefon", "telefonnummer", "anrufen",
];
export const ADDRESS_CUES = [
  "adresse", "se trouve", "situe", "situee", "ou aller", "ou se rendre",
  "address", "where is", "where are", "located", "where do i go", "where can i go",
  "wo ist", "wo befindet", "wo sind", "wohin",
];
export const URL_CUES = [
  "site", "site web", "site internet", "lien", "url",
  "website", "link", "web page", "webpage",
  "webseite", "internetseite",
];

export const PAGE_REFERENCE_CUES = ["sur cette page", "cette page", "on this page", "this page", "auf dieser seite", "diese seite"];

export const INTERROGATIVES = new Set(`
    comment quand combien ou quel quelle quels quelles pourquoi que quoi qui
    how when where which what why who
    wie wann wo welche welcher welches warum was wer
`.split(/\s+/).filter(Boolean));

export const MONTHS =
  "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|" +
  "january|february|march|april|may|june|july|august|september|october|november|december|" +
  "januar|februar|m[aä]rz|juni|juli|oktober|dezember";

// Anchor patterns per answer type (SPEC §2), as Python regex strings: the keyword `text` is this
// string, byte for byte; `pyRegex` compiles it for JS.
export const ANCHOR_PATTERNS = {
  amount: "(?:\\d{1,3}(?:[ .]\\d{3})+|\\d+)(?:[.,]\\d+)?\\s?(?:€|euros?|eur)\\b",
  date: `\\b\\d{1,2}(?:er)?\\s+(?:${MONTHS})\\s+\\d{4}\\b|\\b\\d{1,2}[./-]\\d{1,2}[./-]\\d{2,4}\\b|\\b(?:${MONTHS})\\s+\\d{4}\\b`,
  phone: "(?:\\+352|00352)?\\s?(?:\\d[\\s.-]?){5,9}\\d\\b",
  address: "\\bL-?\\s?\\d{4}\\b",
  url: "https?://\\S+|\\b[\\w-]+\\.(?:lu|com|eu|org|net)\\b",
  duration: "\\b\\d+\\s?(?:jours?|mois|ans?|annees?|semaines?|heures?|days?|months?|years?|weeks?|hours?|tagen?|monaten?|jahren?|wochen?)\\b",
};
const _ANCHOR_RE = Object.fromEntries(Object.entries(ANCHOR_PATTERNS).map(([k, p]) => [k, pyRegex(p)]));

// ----------------------------------------------------------------------------- helpers

const _CUE_RE = new Map();
function cueRegex(cue) {
  let rx = _CUE_RE.get(cue);
  if (!rx) {
    rx = new RegExp(`(?<![\\p{L}\\p{N}_-])${escapeRegex(cue)}(?![\\p{L}\\p{N}_-])`, "u");
    _CUE_RE.set(cue, rx);
  }
  return rx;
}

/** The first cue present as a whole word or phrase, else null. */
export function _has_cue(folded_text, cues) {
  const padded = ` ${folded_text} `;
  for (const cue of cues) {
    if (cue === "€") {
      if (folded_text.includes("€")) return cue;
      continue;
    }
    if (cueRegex(cue).test(padded)) return cue;
  }
  return null;
}

export function _starts_with_frame(folded_text, frames) {
  const stripped = folded_text.replace(/^[ ¿?!,.;:'"]+/u, "");
  for (const frame of frames) {
    if (stripped.startsWith(frame + " ") || stripped === frame || stripped.startsWith(frame + "'")) return frame;
  }
  return null;
}

export function _answer_shape(folded_text) {
  const cue = _has_cue(folded_text, LISTING_CUES);
  if (cue) return ["listing", `answer_shape=listing: cue '${cue}'`];
  return ["single", "answer_shape=single: no listing cue"];
}

export function _answer_type(folded_text) {
  const frame = _starts_with_frame(folded_text, BOOLEAN_FRAMES);
  if (frame) return ["boolean", `answer_type=boolean: the question opens with '${frame}'`];
  const ordered = [
    ["duration", DURATION_CUES],
    ["amount", AMOUNT_CUES],
    ["date", DATE_CUES],
    ["phone", PHONE_CUES],
    ["address", ADDRESS_CUES],
    ["url", URL_CUES],
  ];
  for (const [answer_type, cues] of ordered) {
    const cue = _has_cue(folded_text, cues);
    if (cue) return [answer_type, `answer_type=${answer_type}: cue '${cue}'`];
  }
  for (const answer_type of Object.keys(ANCHOR_PATTERNS)) {
    if (["amount", "date", "phone"].includes(answer_type) && reSearch(_ANCHOR_RE[answer_type], folded_text)) {
      return [answer_type, `answer_type=${answer_type}: the question itself holds a ${answer_type} pattern`];
    }
  }
  return ["text", "answer_type=text: no typed cue"];
}

export function _answer_context(answer_shape, answer_type) {
  if (answer_shape === "listing") return "section";
  if (["amount", "date", "boolean", "phone", "url", "duration"].includes(answer_type)) return "line";
  return "paragraph";
}

export function _doc_ids(frame) {
  if (!frame || frame.length === 0 || !("doc_id" in frame[0])) return new Set();
  return new Set(frame.map((r) => String(r.doc_id)));
}

/** `corpus_index.tags` may be a list, a JSON-ish string or a comma-separated string. */
export function _tags_of(row) {
  const tags = row.tags;
  if (tags === null || tags === undefined || (typeof tags === "number" && Number.isNaN(tags))) return [];
  if (typeof tags === "string") {
    return tags
      .split(",")
      .map((t) => t.replace(/^[ '"[\]]+|[ '"[\]]+$/g, ""))
      .filter((t) => t);
  }
  return Array.from(tags, (t) => String(t));
}

/**
 * The heading whose every content word is in the question (fuzzy by one edit on long words).
 * Longest heading wins; a tie goes to the reader's page, then to the first row of toc_df.
 */
export function _toc_section_hint(stems, toc_df, current_page) {
  if (!toc_df || toc_df.length === 0 || !("title" in toc_df[0]) || !stems.length) return [null, null];
  const question_stems = new Set(stems);
  let best = null; // [-n_tokens, not_on_page, row_order, title]
  toc_df.forEach((row, order) => {
    const title = String(row.title);
    const title_stems = content_tokens(fold_tokens(title)).map(stem);
    if (!title_stems.length) return;
    if (!title_stems.every((s) => _stem_in(s, question_stems))) return;
    if (title_stems.length === 1 && title_stems[0].length < 4) return; // a one-word heading of three letters is too easy to hit
    const on_page = current_page !== null && current_page !== undefined && String(row.doc_id ?? "") === current_page ? 0 : 1;
    const key = [-title_stems.length, on_page, order, title];
    if (best === null || compareTuple(key, best) < 0) best = key;
  });
  if (best === null) return [null, null];
  const title = best[3];
  return [title, `toc_section_hint='${title}': every word of this heading is in the question`];
}

function compareTuple(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

export function _stem_in(s, stems) {
  if (stems.has(s)) return true;
  if (s.length >= 6) {
    for (const q of stems) if (q.length >= 6 && damerau_levenshtein(s, q, 1) <= 1) return true;
  }
  return false;
}

const _STRIP_PUNCT = " ?!.;,";
function stripPunct(s) {
  let a = 0;
  let b = s.length;
  while (a < b && _STRIP_PUNCT.includes(s[a])) a++;
  while (b > a && _STRIP_PUNCT.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

/** The "et / and" test: two clauses that each carry a subject are two questions. */
export function _decompose(corrected) {
  const parts = corrected
    .split(/\s+(?:et|and|und)\s+|\s*;\s*/u)
    .map((p) => stripPunct(p))
    .filter((p) => p);
  if (parts.length < 2) return [Decomposition(), "decomposition=single: no 'et / and' between two clauses"];
  for (const part of parts) {
    const folded = fold_tokens(part);
    const content = content_tokens(folded);
    const has_interrogative = folded.some((t) => INTERROGATIVES.has(t));
    if (!(content.length >= 2 || (content.length >= 1 && has_interrogative))) {
      return [Decomposition(), `decomposition=single: '${part}' is not a clause of its own`];
    }
  }
  return [
    Decomposition({ pattern: "independent", sub_questions: parts }),
    `decomposition=independent: ${parts.length} clauses, each with its own content words`,
  ];
}

export function _clarification_text(language, reason, term, labels, default_label) {
  const lang = ["fr", "en", "de"].includes(language) ? language : "fr";
  const options = labels.join(", ");
  const texts = {
    fr: {
      too_short: "Votre question est trop courte. Dites-moi ce que vous cherchez, par exemple « comment immatriculer ma voiture ? ».",
      no_content_words: "Je ne vois pas de mot-clé dans votre question. De quel sujet du guide s'agit-il ?",
      pronoun_only: `« ${term} » ne me dit pas de quoi il s'agit. De quel sujet du guide parlez-vous ?`,
      single_term_multiple_concepts: `« ${term} » peut vouloir dire : ${options}. Je propose « ${default_label} » ; précisez si vous pensiez à autre chose.`,
    },
    en: {
      too_short: "Your question is too short. Tell me what you are looking for, for example 'how do I register my car?'.",
      no_content_words: "I see no keyword in your question. Which subject of the guide do you mean?",
      pronoun_only: `'${term}' does not tell me what it is. Which subject of the guide do you mean?`,
      single_term_multiple_concepts: `'${term}' can mean: ${options}. I propose '${default_label}'; say so if you meant another one.`,
    },
    de: {
      too_short: "Ihre Frage ist zu kurz. Sagen Sie mir, was Sie suchen, zum Beispiel 'wie melde ich mein Auto an?'.",
      no_content_words: "Ich sehe kein Stichwort in Ihrer Frage. Welches Thema des Leitfadens meinen Sie?",
      pronoun_only: `'${term}' sagt mir nicht, worum es geht. Welches Thema des Leitfadens meinen Sie?`,
      single_term_multiple_concepts: `'${term}' kann bedeuten: ${options}. Ich schlage '${default_label}' vor; sagen Sie es, wenn Sie etwas anderes meinten.`,
    },
  };
  return texts[lang][reason];
}

/** The candidate whose topic is the reader's page, else the one most pages are tagged with. */
export function _proposed_default(candidates, dictionary, corpus_index, current_page) {
  let page_topic = null;
  if (current_page !== null && current_page !== undefined && corpus_index && corpus_index.length && "topic" in corpus_index[0]) {
    const rows = corpus_index.filter((r) => String(r.doc_id) === current_page);
    if (rows.length) page_topic = String(rows[0].topic);
  }
  if (page_topic !== null) {
    const on_page = candidates.filter(([, t]) => t === page_topic).map(([c]) => c);
    if (on_page.length) return [on_page[0], `its topic '${page_topic}' is the topic of the page being read (${current_page})`];
  }
  // A tag counts for a candidate when it is the concept id or any of its variants, folded.
  const counts = new Map(candidates.map(([c]) => [c, 0]));
  const forms = new Map(candidates.map(([c]) => [c, dictionary.tag_forms(c)]));
  if (corpus_index && corpus_index.length && "tags" in corpus_index[0]) {
    for (const row of corpus_index) {
      const tags = new Set(_tags_of(row).map(fold));
      for (const [concept, concept_forms] of forms) {
        if (Array.from(tags).some((t) => concept_forms.has(t))) counts.set(concept, counts.get(concept) + 1);
      }
    }
  }
  const best = sortedBy(Array.from(counts.entries()), ([c, n]) => [-n, c])[0];
  if (best[1] === 0) return [best[0], "no page of the corpus is tagged with any candidate; first candidate by name"];
  return [best[0], `${best[1]} page(s) of the corpus are tagged with it, more than any other candidate`];
}

const _VOCABULARY_CACHE = new WeakMap();
let _WEAK_WORDS = null;

/** The weak words the parser uses when none is passed; `set_weak_words` installs the JSON's block. */
export function weak_words() {
  if (_WEAK_WORDS === null) _WEAK_WORDS = new WeakWords({});
  return _WEAK_WORDS;
}

export function set_weak_words(weak) {
  _WEAK_WORDS = weak;
}

/** The corpus vocabulary, built once per `line_df` array; dictionary words count as known. */
export function vocabulary_for(line_df, dictionary = null) {
  const key = line_df || _VOCABULARY_CACHE;
  const cached = _VOCABULARY_CACHE.get(key);
  if (cached) return cached;
  const known = dictionary !== null ? dictionary.terms() : [];
  const vocabulary = Vocabulary.from_line_df(line_df, "text", { known_terms: known });
  _VOCABULARY_CACHE.set(key, vocabulary);
  return vocabulary;
}

// ----------------------------------------------------------------------------- the parser

/** Normalise, detect, extract, decompose, and decide whether to ask one clarification. */
export function parse_question(
  question,
  { line_df, toc_df, corpus_index, dictionary, current_page = null, vocabulary = null, abbreviations = null, weak = null },
) {
  const notes = [];
  vocabulary = vocabulary || vocabulary_for(line_df, dictionary);
  weak = weak || weak_words();
  const normalized = normalize_question(question, { vocabulary, abbreviations });
  for (const [short, long] of normalized.expansions) notes.push(`abbreviation '${short}' expanded to '${long}'`);
  for (const c of normalized.corrections) {
    notes.push(`spelling '${c.original}' corrected to '${c.display}' (distance ${c.distance}, corpus frequency ${c.frequency})`);
  }

  const folded_text = normalized.folded;
  const matches = dictionary.match_concepts(normalized.content);
  let language = normalized.language;
  if (language === "unknown") {
    const votes = {};
    for (const m of matches) votes[m.language] = (votes[m.language] || 0) + 1;
    language = detect_language(normalized.folded_tokens, votes);
    if (language !== "unknown") notes.push(`language=${language}: no stop word voted, the matched dictionary variants did`);
    else notes.push("language=unknown: no stop word and no dictionary variant voted");
  } else {
    notes.push(`language=${language}: stop-word vote`);
  }

  // -- shape, type, context
  let note;
  let answer_shape;
  let answer_type;
  [answer_shape, note] = _answer_shape(folded_text);
  notes.push(note);
  [answer_type, note] = _answer_type(folded_text);
  notes.push(note);
  const answer_context = _answer_context(answer_shape, answer_type);

  // -- keywords
  const keywords = [];
  const seen_folded = new Set();
  const surface_by_folded = new Map();
  normalized.tokens.forEach((token, i) => {
    const folded = normalized.folded_tokens[i];
    if (!surface_by_folded.has(folded)) surface_by_folded.set(folded, token);
  });
  const strong = []; // content words that are not weak: the ones that can carry a subject
  for (const folded of normalized.content) {
    if (seen_folded.has(folded) || isDigits(folded)) continue;
    seen_folded.add(folded);
    const is_weak = weak.has(folded);
    const in_corpus = vocabulary.frequency(folded) > 0;
    if (!is_weak) strong.push(folded);
    // A word absent from the corpus stays a keyword at full weight: the absence sweep must be able
    // to report zero hits for "sapin" or "noël", not silently drop them.
    if (!in_corpus) notes.push(`'${surface_by_folded.get(folded) ?? folded}' is in no line of the corpus (kept, in_corpus=false)`);
    keywords.push(
      Keyword({
        text: surface_by_folded.get(folded) ?? folded,
        weight: is_weak ? WEAK_WEIGHT : 1.0,
        source: "direct",
        weak: is_weak,
        in_corpus,
      }),
    );
  }
  if (keywords.some((k) => k.weak)) {
    notes.push("weak words (weight 0.3): " + keywords.filter((k) => k.weak).map((k) => k.text).join(", "));
  }
  for (const m of matches) notes.push(`concept '${m.concept}' (${m.topic}) matched by '${m.keyword}' [${m.language}, ${m.priority}]`);
  for (const variant of dictionary.expand(matches)) {
    const text = variant.keyword.toLowerCase();
    const folded = fold(text);
    if (seen_folded.has(folded)) continue;
    seen_folded.add(folded);
    keywords.push(
      Keyword({
        text,
        weight: pyRound(DICTIONARY_WEIGHT * variant.weight, 3),
        source: "expert_dictionary",
        concept: variant.concept,
        in_corpus: content_tokens(fold_tokens(text)).every((t) => vocabulary.frequency(t) > 0),
      }),
    );
  }
  if (answer_type in ANCHOR_PATTERNS) {
    keywords.push(Keyword({ text: ANCHOR_PATTERNS[answer_type], weight: 1.0, source: "anchor", is_regex: true }));
    notes.push(`anchor regex for ${answer_type} added`);
  }
  for (const folded of normalized.content) {
    const pattern = `\\b${folded}\\b`;
    if (isDigits(folded) && !seen_folded.has(pattern)) {
      seen_folded.add(pattern);
      keywords.push(Keyword({ text: pattern, weight: 1.0, source: "anchor", is_regex: true }));
      notes.push(`anchor for the number '${folded}' typed in the question`);
    }
  }

  // -- structural hints
  let pages_hint = null;
  const page_cue = _has_cue(folded_text, PAGE_REFERENCE_CUES);
  if (current_page) {
    pages_hint = [current_page];
    const known_pages = new Set([..._doc_ids(corpus_index), ..._doc_ids(toc_df), ..._doc_ids(line_df)]);
    if (known_pages.size && !known_pages.has(current_page)) {
      notes.push(`pages_hint=['${current_page}'] from the reader's page, which the tables do not list`);
    } else {
      notes.push(`pages_hint=['${current_page}'] from the reader's page` + (page_cue ? ` ('${page_cue}' confirms it)` : ""));
    }
  } else if (page_cue) {
    notes.push(`the question says '${page_cue}' but no current page was given: pages_hint stays empty`);
  }
  const [section_hint, hint_note] = _toc_section_hint(normalized.stems(), toc_df, current_page);
  if (hint_note) notes.push(hint_note);

  // -- topic
  let topic;
  [topic, note] = _topic_of(matches, corpus_index, current_page);
  notes.push(note);

  // -- decomposition
  let decomposition;
  [decomposition, note] = _decompose(normalized.corrected);
  notes.push(note);

  // -- clarification
  let ambiguity = null;
  let clarification = null;
  let candidate_values = [];
  let proposed_default = null;
  let term = "";
  if (question.trim().length < 2 || !normalized.tokens.length) {
    ambiguity = "too_short";
  } else if (!normalized.content.length && normalized.pronouns_seen.length) {
    ambiguity = "pronoun_only";
    term = surface_by_folded.get(normalized.pronouns_seen[0]) ?? normalized.pronouns_seen[0];
  } else if (!normalized.content.length) {
    ambiguity = "no_content_words";
  } else if (!strong.length && !matches.length) {
    // "comment obtenir des documents ?": only weak words and no concept, so no subject;
    // "ça marche comment ?": the same, but a pronoun stands where the subject should be.
    if (normalized.pronouns_seen.length) {
      ambiguity = "pronoun_only";
      term = surface_by_folded.get(normalized.pronouns_seen[0]) ?? normalized.pronouns_seen[0];
      notes.push("every content word is a weak word and a pronoun stands for the subject");
    } else {
      ambiguity = "no_content_words";
      notes.push("every content word is a weak word: no subject");
    }
  } else if (strong.length === 1) {
    const candidates = dictionary.concepts_for_token(strong[0]);
    if (new Set(candidates.map(([, t]) => t)).size >= 2) {
      ambiguity = "single_term_multiple_concepts";
      term = surface_by_folded.get(strong[0]) ?? strong[0];
      candidate_values = candidates.map(([c]) => c);
      let why;
      [proposed_default, why] = _proposed_default(candidates, dictionary, corpus_index, current_page);
      notes.push(`proposed_default='${proposed_default}': ${why}`);
      topic = dictionary.topic_of(proposed_default);
      notes.push(`scope topic '${topic}' follows the proposed default until the reader says otherwise`);
    }
  }
  if (ambiguity !== null) {
    const labels = candidate_values.map((c) => `${dictionary.label_of(c, language)} (${dictionary.topic_of(c)})`);
    const default_label = proposed_default ? dictionary.label_of(proposed_default, language) : null;
    clarification = _clarification_text(language, ambiguity, term, labels, default_label);
    notes.push(`clarification: ${ambiguity}`);
  }

  return ParsedQuestion({
    question_id: question_id_of(question),
    original_question: question,
    corrected_question: normalized.corrected,
    language,
    keywords,
    answer_shape,
    answer_type,
    structural_hints: StructuralHints({ pages_hint, toc_section_hint: section_hint, answer_context }),
    scope_filters: ScopeFilters({ topic }),
    decomposition,
    suggested_clarification: clarification,
    ambiguity_reason: ambiguity,
    candidate_values,
    proposed_default,
    parsing_notes: notes,
  });
}

/** The topic the matched concepts vote for, weighted by variant weight; the page breaks ties. */
export function _topic_of(matches, corpus_index, current_page) {
  if (!matches.length) return [null, "scope topic=None: no dictionary concept matched"];
  const votes = new Map();
  for (const m of matches) votes.set(m.topic, pyRound((votes.get(m.topic) ?? 0.0) + m.weight, 3));
  const top = Math.max(...votes.values());
  const leaders = sortedStrings(Array.from(votes.entries()).filter(([, v]) => v === top).map(([t]) => t));
  if (leaders.length === 1) {
    return [leaders[0], `scope topic='${leaders[0]}': the matched concepts vote ${pyDictRepr(Array.from(votes.entries()))}`];
  }
  if (current_page !== null && current_page !== undefined && corpus_index && corpus_index.length && "topic" in corpus_index[0]) {
    const rows = corpus_index.filter((r) => String(r.doc_id) === current_page);
    if (rows.length && leaders.includes(String(rows[0].topic))) {
      const page_topic = String(rows[0].topic);
      return [page_topic, `scope topic='${page_topic}': a tie ${pyListRepr(leaders)}, broken by the page being read`];
    }
  }
  return [null, `scope topic=None: a tie between ${pyListRepr(leaders)} and no page to break it`];
}

export { Abbreviations, Dictionary, Vocabulary, WeakWords };
