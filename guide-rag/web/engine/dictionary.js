// Port of guide_rag/question/dictionary.py: the expert dictionary (concepts, keyword variants) and
// the matcher over question tokens. The YAML under dictionary/ is the asset; web/build_data.py
// exports it to web/data/dictionary.json, which `Dictionary.load` reads.

import { sortedBy, sortedStrings, tupleKey } from "./_py.js";
import { content_tokens, fold, fold_tokens } from "./normalize.js";
import { stem } from "./stopwords.js";

export const TOPICS = ["housing", "vehicle", "liability", "administration", "health", "work", "money", "other"];
export const LANGUAGES = ["fr", "en", "de", "lb"];
export const PRIORITIES = ["primary", "secondary"];

// A variant with too short a match key would fire on noise: "a", "l", "1". Two is enough for "rc".
export const MIN_KEY_CHARS = 2;
const _LANGUAGE_ORDER = { fr: 0, en: 1, de: 2, lb: 3 };

/** The stems of the folded content tokens of a variant: what the question is compared to. */
export function match_key(keyword) {
  return content_tokens(fold_tokens(keyword)).map(stem);
}

export class Variant {
  constructor(fields) {
    Object.assign(this, fields); // concept, topic, language, keyword, priority, weight, key
  }
}

/** A variant found in the question: `start..end` are token positions (end exclusive). */
export class ConceptMatch {
  constructor(concept, topic, keyword, language, priority, weight, start, end) {
    this.concept = concept;
    this.topic = topic;
    this.keyword = keyword;
    this.language = language;
    this.priority = priority;
    this.weight = weight;
    this.start = start;
    this.end = end;
  }

  get length() {
    return this.end - this.start;
  }
}

/** Concepts and variants, loaded once, matched many times. */
export class Dictionary {
  constructor(concepts_df, concept_keywords_df) {
    // The two frames as arrays of records, column for column as in Python.
    this.concepts_df = concepts_df.map((r) => ({ concept: r.concept, topic: r.topic, definition: r.definition }));
    this.concept_keywords_df = concept_keywords_df.map((r) => ({
      concept: r.concept,
      language: r.language,
      keyword: String(r.keyword),
      priority: r.priority,
      weight: r.weight,
    }));
    this._validate();
    this._topic = new Map(this.concepts_df.map((r) => [r.concept, r.topic]));
    this._definition = new Map(this.concepts_df.map((r) => [r.concept, r.definition]));
    this._variants = [];
    this._by_key = new Map();
    this._by_concept = new Map();
    for (const row of this.concept_keywords_df) {
      const key = match_key(String(row.keyword));
      if (!key.length || key.reduce((n, k) => n + k.length, 0) < MIN_KEY_CHARS) {
        throw new Error(`variant '${row.keyword}' of ${row.concept} has no usable match key`);
      }
      const variant = new Variant({
        concept: String(row.concept),
        topic: this._topic.get(String(row.concept)),
        language: String(row.language),
        keyword: String(row.keyword),
        priority: String(row.priority),
        weight: Number(row.weight),
        key,
      });
      this._variants.push(variant);
      const k = tupleKey(...key);
      if (!this._by_key.has(k)) this._by_key.set(k, []);
      this._by_key.get(k).push(variant);
      if (!this._by_concept.has(variant.concept)) this._by_concept.set(variant.concept, []);
      this._by_concept.get(variant.concept).push(variant);
    }
    this._max_key_len = Math.max(1, ...Array.from(this._by_key.keys(), (k) => k.split("\u0000").length));
  }

  // -- construction

  /** From web/data/dictionary.json ({concepts: [...], keywords: [...]}), the export of the YAML. */
  static load(data) {
    const concepts = (data && data.concepts) || [];
    const keywords = (data && data.keywords) || [];
    return new Dictionary(concepts, keywords);
  }

  /** Fail loudly at load time: a broken dictionary must not parse questions quietly. */
  _validate() {
    const concepts = this.concepts_df.map((r) => r.concept);
    if (new Set(concepts).size !== concepts.length) throw new Error("concepts.yaml repeats a concept");
    const bad_topics = sortedStrings(this.concepts_df.map((r) => r.topic).filter((t) => !TOPICS.includes(t)));
    if (bad_topics.length) throw new Error(`concepts.yaml uses topics outside SPEC §1: ${JSON.stringify(bad_topics)}`);
    const known = new Set(concepts);
    const unknown = sortedStrings(this.concept_keywords_df.map((r) => r.concept).filter((c) => !known.has(c)));
    if (unknown.length) throw new Error(`keywords.yaml names concepts absent from concepts.yaml: ${JSON.stringify(unknown)}`);
    const bad_lang = sortedStrings(this.concept_keywords_df.map((r) => r.language).filter((l) => !LANGUAGES.includes(l)));
    if (bad_lang.length) throw new Error(`keywords.yaml uses unknown languages: ${JSON.stringify(bad_lang)}`);
    const bad_priority = sortedStrings(this.concept_keywords_df.map((r) => r.priority).filter((p) => !PRIORITIES.includes(p)));
    if (bad_priority.length) throw new Error(`keywords.yaml uses unknown priorities: ${JSON.stringify(bad_priority)}`);
    const with_variant = new Set(this.concept_keywords_df.map((r) => r.concept));
    const without_variant = sortedStrings(concepts.filter((c) => !with_variant.has(c)));
    if (without_variant.length) throw new Error(`concepts without any variant: ${JSON.stringify(without_variant)}`);
  }

  // -- lookups

  get concepts() {
    return this.concepts_df.map((r) => r.concept);
  }

  topic_of(concept) {
    return this._topic.get(concept);
  }

  definition_of(concept) {
    return this._definition.get(concept);
  }

  variants_of(concept) {
    return Array.from(this._by_concept.get(concept) || []);
  }

  /** Every variant keyword, for the vocabulary: dictionary words are never typos. */
  terms() {
    return this._variants.map((v) => v.keyword);
  }

  /** The folded strings a corpus tag may use for the concept: its id, with spaces, its variants. */
  tag_forms(concept) {
    const forms = new Set([fold(concept), fold(concept.replace(/_/g, " "))]);
    for (const v of this._by_concept.get(concept) || []) forms.add(fold(v.keyword));
    return forms;
  }

  /** The primary variant in the language, else in French, else the concept id. */
  label_of(concept, language) {
    const variants = this._by_concept.get(concept) || [];
    for (const lang of [language, "fr", "en"]) {
      for (const v of variants) if (v.language === lang && v.priority === "primary") return v.keyword;
    }
    return concept;
  }

  /** [concept, topic] pairs whose single-word variant matches a folded token; sorted. */
  concepts_for_token(token) {
    const key = tupleKey(stem(fold(token)));
    const found = new Map();
    for (const v of this._by_key.get(key) || []) found.set(tupleKey(v.concept, v.topic), [v.concept, v.topic]);
    return sortedBy(Array.from(found.values()), (p) => p);
  }

  // -- matching

  /**
   * Every variant found as a contiguous run of the question's content tokens. A longer variant
   * covering a shorter one at the same place wins; one match per concept and place, the primary,
   * heaviest variant representing it. Order: position, then longest, then concept name.
   */
  match_concepts(tokens) {
    const stems = Array.from(tokens, stem);
    const found = [];
    for (let start = 0; start < stems.length; start++) {
      const maxLen = Math.min(this._max_key_len, stems.length - start);
      for (let length = 1; length <= maxLen; length++) {
        const key = tupleKey(...stems.slice(start, start + length));
        for (const v of this._by_key.get(key) || []) {
          found.push(new ConceptMatch(v.concept, v.topic, v.keyword, v.language, v.priority, v.weight, start, start + length));
        }
      }
    }
    const kept = found.filter((m) => !found.some((o) => o.length > m.length && o.start <= m.start && m.end <= o.end));
    const rank = (m) => [m.priority !== "primary", -m.weight, _LANGUAGE_ORDER[m.language] ?? 9, m.keyword];
    const best = new Map();
    for (const m of kept) {
      const slot = tupleKey(m.concept, m.start, m.end);
      const current = best.get(slot);
      if (current === undefined || compareRank(rank(m), rank(current)) < 0) best.set(slot, m);
    }
    return sortedBy(Array.from(best.values()), (m) => [m.start, -m.length, m.concept]);
  }

  /** Every variant, in every language, of the given concepts; first concept first. */
  expand(concepts) {
    const seen = [];
    for (const item of concepts) {
      const concept = item instanceof ConceptMatch ? item.concept : item;
      if (!seen.includes(concept)) seen.push(concept);
    }
    const out = [];
    for (const concept of seen) out.push(...(this._by_concept.get(concept) || []));
    return out;
  }

  // -- reporting

  size() {
    const counts = {};
    for (const r of this.concept_keywords_df) counts[r.language] = (counts[r.language] || 0) + 1;
    const out = { concepts: this.concepts_df.length, variants: this.concept_keywords_df.length };
    for (const k of sortedStrings(Object.keys(counts))) out[`variants_${k}`] = counts[k];
    return out;
  }
}

function compareRank(a, b) {
  for (let i = 0; i < a.length; i++) {
    const x = typeof a[i] === "boolean" ? (a[i] ? 1 : 0) : a[i];
    const y = typeof b[i] === "boolean" ? (b[i] ? 1 : 0) : b[i];
    if (x < y) return -1;
    if (x > y) return 1;
  }
  return 0;
}
