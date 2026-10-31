// Port of guide_rag/retrieval/contracts.py: the minimal input of bricks 3 and 4 (ParsedQuestion,
// ExecutionPlan, Tables) read duck-typed, plus the question terms, content words and coverage.

import { isMapping, pyRound, pySum, sortedStrings } from "./_py.js";
import { content_tokens, fold_tokens } from "./normalize.js";
import { fold, is_weak, phrase_in, stem, stems, tokens } from "./text.js";

export const WEAK_WEIGHT = 0.3; // a generic content word counts this much in the coverage of a question

/** The contract ParsedQuestion: the fields of SPEC §2 that retrieval and generation read, extras kept. */
export function ParsedQuestion(data) {
  return {
    question_id: data.question_id,
    original_question: data.original_question,
    corrected_question: data.corrected_question,
    language: data.language ?? "unknown",
    keywords: (data.keywords ?? []).map((k) => Keyword(k)),
    answer_shape: data.answer_shape ?? "single",
    answer_type: data.answer_type ?? "text",
    structural_hints: StructuralHints(data.structural_hints ?? {}),
    decomposition: Decomposition(data.decomposition ?? {}),
    suggested_clarification: data.suggested_clarification ?? null,
    ambiguity_reason: data.ambiguity_reason ?? null,
    candidate_values: data.candidate_values ?? [],
    proposed_default: data.proposed_default ?? null,
    ...extras(data, [
      "question_id", "original_question", "corrected_question", "language", "keywords", "answer_shape", "answer_type",
      "structural_hints", "decomposition", "suggested_clarification", "ambiguity_reason", "candidate_values", "proposed_default",
    ]),
  };
}

function extras(data, known) {
  const out = {};
  for (const [k, v] of Object.entries(data)) if (!known.includes(k)) out[k] = v;
  return out;
}

export function Keyword(k) {
  return { text: k.text, weight: k.weight ?? 1.0, source: k.source ?? "direct", concept: k.concept ?? null, is_regex: k.is_regex ?? false, ...extras(k, ["text", "weight", "source", "concept", "is_regex"]) };
}

export function StructuralHints(h) {
  return { pages_hint: h.pages_hint ?? null, toc_section_hint: h.toc_section_hint ?? null, answer_context: h.answer_context ?? "paragraph", ...extras(h, ["pages_hint", "toc_section_hint", "answer_context"]) };
}

export function Decomposition(d) {
  return { pattern: d.pattern ?? "single", sub_questions: d.sub_questions ?? [], ...extras(d, ["pattern", "sub_questions"]) };
}

export function Activation(a) {
  return { on: a.on, reason: a.reason };
}

/** `activations` maps a flag name to {on, reason}; the dispatcher's names are the keys. */
export function ExecutionPlan(data) {
  const activations = {};
  for (const [k, v] of Object.entries((data && data.activations) || {})) activations[k] = Activation(v);
  return { activations };
}

// The dispatcher's flags and the default the retrieval assumes when a plan does not carry them.
export const DEFAULT_ACTIVATIONS = {
  use_keywords: [true, "keyword detectors always run"],
  use_toc: [true, "default: the toc is a first-class signal"],
  use_row_level: [false, "default: the question names no table column and asks for no amount or date"],
  use_embeddings: [false, "no vocabulary mismatch expected beyond the dictionary; keywords prove absence"],
  use_llm_arbiter: [false, "no key configured"],
  use_llm_generation: [false, "no key configured"],
  sweep_for_absence: [true, "always on"],
  current_page_boost: [false, "no pages_hint"],
};

/** The brick-1 tables (SPEC §1) as arrays of records; `parse_coverage` is the coverage JSON. */
export class Tables {
  constructor({ line_df, toc_df, row_df = null, corpus_index = null, page_df = null, cross_ref_df = null, parse_coverage = null, index_version = null, extra = {} }) {
    this.line_df = line_df;
    this.toc_df = toc_df;
    this.row_df = row_df;
    this.corpus_index = corpus_index;
    this.page_df = page_df;
    this.cross_ref_df = cross_ref_df;
    this.parse_coverage = parse_coverage;
    this.index_version = index_version;
    this.extra = extra;
  }
}

// --- duck-typed readers -------------------------------------------------------------------------

/** Read `name` from an object or a mapping; missing gives `default` (an explicit null is kept). */
export function attr(obj, name, dflt = null) {
  if (obj === null || obj === undefined) return dflt;
  if (obj instanceof Map) return obj.has(name) ? obj.get(name) : dflt;
  if (typeof obj !== "object" && typeof obj !== "function") return dflt;
  const v = obj[name];
  return v === undefined ? dflt : v;
}

export function as_tables(tables) {
  if (tables instanceof Tables) return tables;
  return new Tables({
    line_df: attr(tables, "line_df"),
    toc_df: attr(tables, "toc_df"),
    row_df: attr(tables, "row_df"),
    corpus_index: attr(tables, "corpus_index"),
    page_df: attr(tables, "page_df"),
    cross_ref_df: attr(tables, "cross_ref_df"),
    parse_coverage: attr(tables, "parse_coverage"),
    index_version: attr(tables, "index_version"),
  });
}

/** [on, reason] of a flag; the plan may carry `activations[name]` or the flag as an attribute. */
export function plan_activation(plan, name) {
  const [default_on, default_reason] = DEFAULT_ACTIVATIONS[name] ?? [false, "not in the plan"];
  const activations = attr(plan, "activations");
  let entry = isMapping(activations) ? attr(activations, name) : null;
  if (entry === null) entry = attr(plan, name);
  if (entry === null || typeof entry === "function") return [default_on, default_reason];
  if (typeof entry === "boolean") return [entry, `plan flag ${name} without a reason`];
  const on = attr(entry, "on", default_on);
  const reason = attr(entry, "reason", default_reason);
  return [Boolean(on), String(reason)];
}

/** Every known flag with its on/reason, for the `_meta` block. */
export function plan_activations(plan) {
  const names = Object.keys(DEFAULT_ACTIVATIONS);
  let activations = attr(plan, "activations") || {};
  if (typeof activations === "function") {
    // brick 2's plan exposes activations() as a method
    try {
      activations = activations();
    } catch (e) {
      activations = {};
    }
  }
  if (isMapping(activations)) for (const name of Object.keys(activations)) if (!names.includes(name)) names.push(name);
  const out = {};
  for (const name of names) {
    let [on, reason] = plan_activation(plan, name);
    if (isMapping(activations) && name in activations) {
      const entry = activations[name];
      on = Boolean(attr(entry, "on", on));
      reason = String(attr(entry, "reason", reason));
    }
    out[name] = { on, reason };
  }
  return out;
}

/** One question keyword, normalised for matching. `concept_key` groups variants of one concept. */
export function Term({ text, weight, source, concept, is_regex, concept_key, weak = false, in_corpus = true }) {
  return { text, weight, source, concept, is_regex, concept_key, weak, in_corpus }; // in_corpus: brick 2's flag
}

export function question_keywords(parsed) {
  return Array.from(attr(parsed, "keywords", []) || []);
}

export function question_text(parsed) {
  return String(attr(parsed, "corrected_question") || attr(parsed, "original_question") || "");
}

/**
 * The deduplicated keywords, each with its concept when the dictionary knows it: (a) brick 2 set
 * it, (b) it is a variant of the concept (folded, then stem-equal for one-word variants), or (c) a
 * multi-word variant of a concept named in the question contains it and occurs in the question.
 * A generic word (text.WEAK_WORDS) weighs WEAK_WEIGHT.
 */
export function question_terms(parsed, variants_by_concept = null) {
  variants_by_concept = variants_by_concept || {};
  const ambiguous = ambiguous_variants(variants_by_concept);
  const by_fold = new Map();
  const by_stem = new Map();
  for (const [concept, variants] of Object.entries(variants_by_concept)) {
    for (const v of variants) {
      if (ambiguous.has(fold(v))) continue; // "assurance" names three concepts: it assigns none
      if (!by_fold.has(fold(v))) by_fold.set(fold(v), concept);
      const vs = stems(v);
      if (vs.length === 1 && !by_stem.has(vs[0])) by_stem.set(vs[0], concept);
    }
  }
  // (c): the stems of multi-word variants present in the question, for the concepts the question names.
  const named = new Set(question_keywords(parsed).filter((kw) => attr(kw, "concept")).map((kw) => String(attr(kw, "concept"))));
  const q_stems = stems(question_text(parsed));
  const phrase_stem_concept = new Map();
  for (const concept of sortedStrings(named)) {
    for (const v of variants_by_concept[concept] || []) {
      const vs = stems(v);
      if (vs.length >= 2 && phrase_in(vs, q_stems)) for (const s of vs) if (!phrase_stem_concept.has(s)) phrase_stem_concept.set(s, concept);
    }
  }

  const seen = new Set();
  const terms = [];
  for (const kw of question_keywords(parsed)) {
    const text = String(attr(kw, "text", "") || "");
    const is_regex = Boolean(attr(kw, "is_regex", false));
    const key = is_regex ? text : fold(text);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const source = String(attr(kw, "source", "direct") || "direct");
    let concept = attr(kw, "concept");
    if (!concept && !is_regex) {
      const ts = stems(text);
      concept = by_fold.get(fold(text)) || (ts.length === 1 ? by_stem.get(ts[0]) ?? null : null);
      if (!concept && ts.length === 1) concept = phrase_stem_concept.get(ts[0]) ?? null;
    }
    let weight = Number(attr(kw, "weight", 1.0) || 1.0);
    let weak = false;
    if (source === "direct" && !is_regex) {
      weak = Boolean(attr(kw, "weak", false)) || weight < 0.5 || is_weak(text);
      if (weak) weight = Math.min(weight, WEAK_WEIGHT);
    }
    const concept_key = concept || (is_regex ? "regex:" + text : tokens(text).join(" ") || text);
    terms.push(Term({ text, weight, source, concept: concept || null, is_regex, concept_key, weak, in_corpus: Boolean(attr(kw, "in_corpus", true)) }));
  }
  return terms;
}

/** Distinct concept keys of the non-regex terms, in question order. */
export function concept_keys(terms) {
  const out = [];
  for (const t of terms) if (!t.is_regex && !out.includes(t.concept_key)) out.push(t.concept_key);
  return out;
}

/** A word the reader typed (a direct keyword) with every phrase that counts as it being covered. */
export function ContentWord({ text, weight, weak, concept_key, phrases, in_corpus = true, has_concept = false }) {
  return { text, weight, weak, concept_key, phrases, in_corpus, has_concept };
}

/** The folded variants that belong to two or more concepts ("assurance", "registration"). */
export function ambiguous_variants(variants_by_concept) {
  const owners = new Map();
  for (const [concept, variants] of Object.entries(variants_by_concept)) {
    for (const v of variants) {
      const f = fold(v);
      if (!owners.has(f)) owners.set(f, new Set());
      owners.get(f).add(concept);
    }
  }
  return new Set(Array.from(owners.entries()).filter(([, cs]) => cs.size >= 2).map(([v]) => v));
}

const sameList = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

/**
 * The direct keywords, each with its own stems and the stems of every variant of its concept
 * (from the question's terms and from the dictionary). A variant shared by several concepts
 * proves none of them, so it never stands in for another word.
 */
export function content_words(terms, variants_by_concept = null) {
  variants_by_concept = variants_by_concept || {};
  const ambiguous = ambiguous_variants(variants_by_concept);
  const by_key = new Map();
  for (const t of terms) {
    // The dictionary's expansions of a concept stand for its words; another word the reader typed
    // does not ("Santé" alone must not cover "complémentaire"). An ambiguous variant ("assurance")
    // stands only for itself.
    if (t.source === "expert_dictionary" && !t.is_regex && stems(t.text).length && !ambiguous.has(fold(t.text))) {
      if (!by_key.has(t.concept_key)) by_key.set(t.concept_key, []);
      by_key.get(t.concept_key).push(stems(t.text));
    }
  }
  for (const [concept, variants] of Object.entries(variants_by_concept)) {
    for (const v of variants) {
      const vs = stems(v);
      if (!by_key.has(concept)) by_key.set(concept, []);
      if (vs.length && !ambiguous.has(fold(v)) && !by_key.get(concept).some((p) => sameList(p, vs))) by_key.get(concept).push(vs);
    }
  }
  const words = [];
  for (const t of terms) {
    if (t.source !== "direct" || t.is_regex || !stems(t.text).length) continue;
    const own = stems(t.text);
    const phrases = [own].concat((by_key.get(t.concept_key) || []).filter((p) => !sameList(p, own)));
    words.push(ContentWord({ text: t.text, weight: t.weight, weak: t.weak, concept_key: t.concept_key, phrases, in_corpus: t.in_corpus, has_concept: t.concept !== null && t.concept !== undefined }));
  }
  return words;
}

/**
 * The words a title must name to count as "an exact title match": the strong words carrying a
 * dictionary concept; when the question names no concept, every strong word.
 */
export function concept_words(words) {
  const strong = words.filter((w) => !w.weak);
  const withConcept = strong.filter((w) => w.has_concept);
  return withConcept.length ? withConcept : strong;
}

/**
 * [covered weight / total weight, covered words, uncovered words] over the given texts. A word is
 * covered when any of its phrases appears whole in any of the texts.
 */
export function coverage(words, stem_lists) {
  const lists = Array.from(stem_lists).filter((s) => s && s.length);
  const total = pySum(words.map((w) => w.weight));
  const covered = [];
  const uncovered = [];
  for (const w of words) {
    // A word brick 2 saw in no line of the corpus is uncovered unless a concept's variants stand for it
    // ("leave" is covered by "congé").
    const hit = (w.in_corpus || w.has_concept) && w.phrases.some((p) => lists.some((ls) => phrase_in(p, ls)));
    (hit ? covered : uncovered).push(w.text);
  }
  if (total <= 0) return [0.0, covered, uncovered];
  const got = pySum(words.filter((w) => covered.includes(w.text)).map((w) => w.weight));
  return [pyRound(got / total, 3), covered, uncovered];
}

const _TITLE_STOP = new Set(
  (
    "le la les l un une des du de d au aux et ou a en pour par sur sous dans avec sans ce cet cette ces son sa ses " +
    "qui que quoi dont qu il elle on ne pas plus est sont faut " +
    "the a an and or of to in on at for with by from is are it its your what which how " +
    "der die das den dem des ein eine und oder zu in an auf fur mit von bei ist sind"
  ).split(/\s+/),
);

/** The words of a heading that carry its subject (brick 2's content_tokens). */
export function title_content_tokens(title) {
  return content_tokens(fold_tokens(title)).filter((t) => t.length > 1);
}

/** Brick 2 absent in Python: a small stop list of the three languages (kept for the mirror, unused when brick 2 loads). */
export function _title_content_tokens_fallback(title) {
  return tokens(title).filter((t) => !_TITLE_STOP.has(t) && t.length > 1);
}

/**
 * "Trust the TOC on exact title matches": every content word of the heading is one of the
 * question's words (or a variant of one of their concepts). "Étapes" is exact for "quelles sont
 * les étapes…"; a FAQ question-heading with words of its own never is.
 */
export function title_exact(title, words) {
  const content = title_content_tokens(title);
  if (!content.length || !words.length) return false;
  for (const tw of content) {
    const s = stem(fold(tw));
    if (!words.some((w) => w.phrases.some((p) => p.includes(s)))) return false;
  }
  return true;
}

/** [pages_hint, toc_section_hint, answer_context]. */
export function hints(parsed) {
  const sh = attr(parsed, "structural_hints");
  const pages = attr(sh, "pages_hint") || [];
  return [Array.from(pages), attr(sh, "toc_section_hint"), String(attr(sh, "answer_context", "paragraph") || "paragraph")];
}

/**
 * concept -> variants, from the dictionary in any of its shapes, merged with the question's own.
 * Accepted shapes: {concept: [variant, ...]}, {concept: [{keyword}, ...]}, an object with
 * `concept_variants()`, brick 2's Dictionary (`concept_keywords_df` or `concepts` + `variants_of`),
 * or an object/mapping with `keywords` rows carrying `concept` and `keyword`.
 */
export function concept_variants(dictionary, parsed = null) {
  const out = {};
  const add = (concept, variant) => {
    if (!concept || !variant) return;
    const key = String(concept);
    if (!(key in out)) out[key] = [];
    const v = String(variant);
    if (!out[key].includes(v)) out[key].push(v);
  };

  if (dictionary !== null && dictionary !== undefined) {
    if (typeof dictionary.concept_variants === "function") {
      for (const [c, vs] of Object.entries(dictionary.concept_variants())) for (const v of vs) add(c, v);
    } else if (isMapping(dictionary) && !("keywords" in dictionary)) {
      for (const [c, vs] of dictionary instanceof Map ? dictionary.entries() : Object.entries(dictionary)) {
        for (const v of Array.isArray(vs) ? vs : [vs]) add(c, typeof v === "string" ? v : attr(v, "keyword", attr(v, "text", v)));
      }
    } else if (dictionary.concept_keywords_df !== null && dictionary.concept_keywords_df !== undefined) {
      for (const row of dictionary.concept_keywords_df) add(row.concept, row.keyword);
    } else if (typeof dictionary.variants_of === "function" && dictionary.concepts !== undefined) {
      for (const c of dictionary.concepts) for (const v of dictionary.variants_of(c)) add(c, attr(v, "keyword", attr(v, "text", v)));
    } else {
      for (const row of attr(dictionary, "keywords", []) || []) add(attr(row, "concept"), attr(row, "keyword", attr(row, "text")));
    }
  }
  for (const kw of parsed !== null ? question_keywords(parsed) : []) {
    if (attr(kw, "is_regex", false)) continue;
    add(attr(kw, "concept"), attr(kw, "text"));
  }
  return out;
}

export function stem_of(text) {
  return stem(fold(text));
}
