// Port of guide_rag/retrieval/detectors.py: the deterministic detectors of SPEC §3. They always
// run; nothing here calls a model. Each detector returns `Hit` rows keyed by (doc_id, line_num).

import { _s, pyRegex, sortedBy } from "./_py.js";
import { fold, phrase_in, stems } from "./text.js";

export const CURRENT_PAGE_FACTOR = 1.3;
export const CO_OCCURRENCE_LINE_FACTOR = 1.5;
export const CO_OCCURRENCE_SECTION_FACTOR = 1.2;

// The anchor kinds, and which answer_type requires which ("two-signal match").
export const ANCHOR_KIND_BY_ANSWER_TYPE = {
  amount: "amount",
  date: "date",
  phone: "phone",
  address: "postal_code",
  url: "url",
  duration: "duration",
  text: null,
  boolean: null,
};

export function Hit(doc_id, line_num, section_id, method, keyword, concept_key, weight, capture = null) {
  return { doc_id, line_num, section_id, method, keyword, concept_key, weight, capture };
}

export function LineRecord(fields) {
  return {
    doc_id: fields.doc_id,
    line_num: fields.line_num,
    text: fields.text,
    element: fields.element,
    section_id: fields.section_id,
    anchor_id: fields.anchor_id,
    is_heading: fields.is_heading,
    stems: fields.stems || [],
  };
}

export { _s };

/** line_df rows as records with their stems computed once; restricted to `doc_ids` when given. */
export function line_records(line_df, doc_ids = null) {
  if (!line_df || line_df.length === 0) return [];
  let df = line_df;
  if (doc_ids !== null) {
    const wanted = new Set(doc_ids);
    df = df.filter((r) => wanted.has(r.doc_id));
  }
  const cols = new Set(Object.keys(line_df[0]));
  const out = [];
  for (const row of sortedBy(df, (r) => [r.doc_id, r.line_num])) {
    const text = _s(row.text);
    const element = cols.has("element") ? _s(row.element) : "";
    const is_heading = cols.has("is_heading") ? Boolean(row.is_heading) : element.startsWith("h");
    out.push(
      LineRecord({
        doc_id: String(row.doc_id),
        line_num: Number(row.line_num),
        text,
        element,
        section_id: _s(row.section_id) || null,
        anchor_id: _s(row.anchor_id) || null,
        is_heading,
        stems: stems(text),
      }),
    );
  }
  return out;
}

// --- keyword_lines ----------------------------------------------------------------------------

/** Every line containing a keyword: whole words, accent-folded, stem-equal; regex terms search raw text. */
export function keyword_lines(lines, terms) {
  const hits = [];
  const compiled = [];
  for (const t of terms) {
    if (t.is_regex) {
      try {
        compiled.push([t, null, pyRegex(t.text, "i")]);
      } catch (e) {
        continue; // a broken pattern from upstream must not stop the deterministic path
      }
    } else {
      const ps = stems(t.text);
      if (ps.length) compiled.push([t, ps, null]);
    }
  }
  for (const line of lines) {
    for (const [t, ps, rx] of compiled) {
      const matched = ps !== null ? phrase_in(ps, line.stems) : rx.test(line.text);
      if (matched) hits.push(Hit(line.doc_id, line.line_num, line.section_id, "keyword_lines", t.text, t.concept_key, t.weight));
    }
  }
  return hits;
}

// --- title_match ------------------------------------------------------------------------------

export function TitleHit(doc_id, section_id, title, keyword, concept_key, weight) {
  return { doc_id, section_id, title, keyword, concept_key, weight };
}

/** Keywords against toc_df.title; a title hit is a strong anchor for the whole section. */
export function title_match(toc_df, terms, doc_ids = null) {
  if (!toc_df || toc_df.length === 0) return [];
  let df = toc_df;
  if (doc_ids !== null) {
    const wanted = new Set(doc_ids);
    df = df.filter((r) => wanted.has(r.doc_id));
  }
  const hits = [];
  const phrase_terms = terms.filter((t) => !t.is_regex && stems(t.text).length).map((t) => [t, stems(t.text)]);
  for (const row of sortedBy(df, (r) => [r.doc_id, r.start_line])) {
    const title = _s(row.title);
    const title_stems = stems(title);
    for (const [t, ps] of phrase_terms) {
      if (phrase_in(ps, title_stems)) hits.push(TitleHit(String(row.doc_id), String(row.section_id), title, t.text, t.concept_key, t.weight));
    }
  }
  return hits;
}

// --- anchor_regex -----------------------------------------------------------------------------

const _FR_MONTHS = { janvier: 1, fevrier: 2, mars: 3, avril: 4, mai: 5, juin: 6, juillet: 7, aout: 8, septembre: 9, octobre: 10, novembre: 11, decembre: 12 };
const _EN_MONTHS = { january: 1, february: 2, march: 3, april: 4, may: 5, june: 6, july: 7, august: 8, september: 9, october: 10, november: 11, december: 12 };
const _DE_MONTHS = { januar: 1, februar: 2, marz: 3, april: 4, mai: 5, juni: 6, juli: 7, august: 8, september: 9, oktober: 10, november: 11, dezember: 12 };
const _MONTHS = { ..._FR_MONTHS, ..._EN_MONTHS, ..._DE_MONTHS };
const _MONTH_ALT = stableLongestFirst(Object.keys(_MONTHS)).join("|");
const _NUMBER_WORDS = {
  un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6, sept: 7, huit: 8,
  neuf: 9, dix: 10, onze: 11, douze: 12, treize: 13, quatorze: 14, quinze: 15, seize: 16,
  vingt: 20, vingts: 20, trente: 30, quarante: 40, cinquante: 50, soixante: 60, cent: 100,
  one: 1, two: 2, three: 3, four: 4, five: 5, seven: 7, eight: 8, nine: 9, ten: 10,
  eleven: 11, twelve: 12, fifteen: 15, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60,
  ein: 1, eine: 1, zwei: 2, drei: 3, vier: 4, funf: 5, sechs: 6, sieben: 7, acht: 8,
  zwolf: 12, zwanzig: 20, dreissig: 30,
};
const _NUM_WORD_ONE = stableLongestFirst(Object.keys(_NUMBER_WORDS)).join("|");
// Compound number words: "vingt-six", "quatre-vingt-dix", "soixante et un", "twenty one".
const _NUM_WORD_ALT = `(?:${_NUM_WORD_ONE})(?:[- ](?:et[- ])?(?:${_NUM_WORD_ONE}))*`;

/** "vingt-six" -> 26, "quatre-vingt-dix" -> 90, "soixante et un" -> 61; null when a part is unknown. */
export function number_word_value(text) {
  const parts = text.trim().split(/[- ]/).filter((p) => p && p !== "et");
  let total = 0.0;
  let run = 0.0;
  for (const p of parts) {
    const v = _NUMBER_WORDS[p];
    if (v === undefined) return null;
    if (v === 20 && run === 4) run = 80; // quatre-vingt(s)
    else if (v === 100 && run) run *= 100;
    else run += v;
  }
  total += run;
  return total || null;
}
const _NUMBER = "\\d{1,3}(?:[ .]\\d{3})*(?:[,.]\\d+)?|\\d+(?:[,.]\\d+)?";

// Python's `sorted(..., key=len, reverse=True)` is stable: equal lengths keep insertion order.
function stableLongestFirst(keys) {
  return sortedBy(keys, (k) => [-k.length]);
}

// Patterns run on the folded text (accents gone, lowercase), so "février" and "Fevrier" both match.
// Written as Python regex strings and compiled by pyRegex, like the originals.
export const PATTERNS = {
  // An amount is a sum of money or a count of time units ("vingt-six jours", "deux mois de loyer"):
  // "combien de jours" asks for an amount whose unit is a day.
  amount: [
    pyRegex(`(?P<value>${_NUMBER})\\s*(?P<currency>€|eur\\b|euros?\\b)`, "g"),
    pyRegex(`(?P<currency>€|eur)\\s*(?P<value>${_NUMBER})`, "g"),
    pyRegex(`(?<![\\w-])(?P<words>${_NUM_WORD_ALT}|\\d+)\\s+(?P<unit>mois de loyer|months? of rent|monatsmieten?)\\b`, "g"),
    pyRegex(
      `(?<![\\w-])(?P<words>${_NUM_WORD_ALT}|\\d+)\\s+(?P<unit>jours?(?: ouvrables)?|semaines?|mois|ans?|annees?|days?|weeks?|months?|years?|tage?n?|wochen?|monate?n?|jahren?)\\b`,
      "g",
    ),
  ],
  date: [
    pyRegex("\\b(?P<y>\\d{4})-(?P<m>\\d{2})-(?P<d>\\d{2})\\b", "g"),
    pyRegex(`\\b(?P<d>\\d{1,2})(?:er|st|nd|rd|th)?\\.?\\s+(?P<month>${_MONTH_ALT})\\s+(?P<y>\\d{4})\\b`, "g"),
    pyRegex(`\\b(?P<month>${_MONTH_ALT})\\s+(?P<d>\\d{1,2})(?:st|nd|rd|th)?,?\\s+(?P<y>\\d{4})\\b`, "g"),
    pyRegex("\\b(?P<d>\\d{1,2})[/.](?P<m>\\d{1,2})[/.](?P<y>\\d{4})\\b", "g"),
  ],
  phone: [
    pyRegex("(?:\\+352|00352)[\\s.-]?\\d(?:[\\s.-]?\\d){5,8}\\b", "g"),
    pyRegex("\\b6\\d{2}[\\s.-]?\\d{3}[\\s.-]?\\d{3}\\b", "g"),
    pyRegex("\\b\\d{2}[\\s.-]\\d{2}[\\s.-]\\d{2}[\\s.-]\\d{2}\\b", "g"),
    pyRegex("\\b11[2-8]\\b", "g"), // the short emergency numbers (112, 113)
  ],
  postal_code: [pyRegex("\\bl-\\s?\\d{4}\\b", "g")],
  url: [pyRegex("\\bhttps?://[^\\s<>\"']+|\\bwww\\.[^\\s<>\"']+", "g")],
  duration: [
    pyRegex(
      `(?<![\\w-])(?P<words>${_NUM_WORD_ALT}|\\d+)\\s+(?P<unit>jours?(?: ouvrables)?|semaines?|mois|ans?|annees?|days?|weeks?|months?|years?|tage?n?|wochen?|monate?n?|jahren?)\\b`,
      "g",
    ),
  ],
};

export function _number(text) {
  let t = text.trim().replace(/ /g, "");
  if (t.includes(",") && t.includes(".")) t = t.replace(/\./g, "").replace(/,/g, ".");
  else if (t.includes(",")) t = t.split(",").pop().length !== 3 ? t.replace(/,/g, ".") : t.replace(/,/g, "");
  else if ((t.match(/\./g) || []).length === 1 && t.split(".").pop().length === 3) t = t.replace(/\./g, "");
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(t)) return null;
  const value = Number(t);
  return Number.isNaN(value) ? null : value;
}

const isDigit = (s) => /^\d+$/.test(s);

/** The typed value of one match; null when the match is not a real value (bad date, no number). */
export function _capture(kind, m) {
  const g = m.groups || {};
  const base = { kind, raw: m[0].trim(), pos: m.index, end: m.index + m[0].length };
  if (kind === "amount") {
    if (g.words !== undefined && g.words !== null) {
      const w = g.words;
      const value = isDigit(w) ? Number(w) : number_word_value(w);
      if (!value) return null;
      return { ...base, value, currency: null, unit: g.unit ?? null };
    }
    const value = _number(g.value);
    if (value === null) return null;
    return { ...base, value, currency: "EUR", unit: null };
  }
  if (kind === "duration") {
    const w = g.words;
    const value = isDigit(w) ? Number(w) : number_word_value(w);
    if (!value) return null;
    return { ...base, value, currency: null, unit: g.unit ?? null };
  }
  if (kind === "date") {
    const y = Number(g.y);
    const month = g.month;
    const mo = month ? _MONTHS[month] : Number(g.m);
    const d = Number(g.d);
    if (!(1 <= mo && mo <= 12 && 1 <= d && d <= 31)) return null;
    return { ...base, iso: `${String(y).padStart(4, "0")}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`, original: base.raw };
  }
  return { ...base, value: base.raw };
}

/** Every typed value of `kind` in one text, left to right, deduplicated by raw text. */
export function find_anchors(text, kind) {
  const folded = fold(text);
  const out = [];
  const seen = new Set();
  for (const rx of PATTERNS[kind] || []) {
    // the more specific patterns come first: "deux mois de loyer" before "deux mois"
    rx.lastIndex = 0;
    for (const m of folded.matchAll(rx)) {
      const cap = _capture(kind, m, text);
      if (cap === null || seen.has(cap.raw)) continue;
      if (out.some((o) => cap.pos < o.end && o.pos < cap.end)) continue; // overlaps a capture already kept
      seen.add(cap.raw);
      out.push(cap);
    }
  }
  const ordered = sortedBy(out, (c) => [c.pos]); // reading order, whatever pattern found them
  for (const c of ordered) delete c.end;
  return ordered;
}

/** Amount/date/phone/postal-code/url hits with their typed capture; the line is the span. */
export function anchor_regex(lines, kind) {
  const hits = [];
  for (const line of lines) {
    for (const cap of find_anchors(line.text, kind)) {
      hits.push(Hit(line.doc_id, line.line_num, line.section_id, "anchor_regex", cap.raw, "anchor:" + kind, 1.0, cap));
    }
  }
  return hits;
}

// --- row_match --------------------------------------------------------------------------------

/** Keywords against row_df.row_serialized; the section comes from line_df by (doc_id, line_num). */
export function row_match(row_df, terms, lines = null, doc_ids = null) {
  if (!row_df || row_df.length === 0) return [];
  let df = row_df;
  if (doc_ids !== null) {
    const wanted = new Set(doc_ids);
    df = df.filter((r) => wanted.has(r.doc_id));
  }
  const section_of = new Map((lines || []).map((l) => [`${l.doc_id}\u0000${l.line_num}`, l.section_id]));
  const phrase_terms = terms.filter((t) => !t.is_regex && stems(t.text).length).map((t) => [t, stems(t.text)]);
  const hits = [];
  for (const row of sortedBy(df, (r) => [r.doc_id, r.line_num])) {
    const serialized = _s(row.row_serialized);
    const row_stems = stems(serialized);
    const doc_id = String(row.doc_id);
    const line_num = Number(row.line_num);
    for (const [t, ps] of phrase_terms) {
      if (phrase_in(ps, row_stems)) hits.push(Hit(doc_id, line_num, section_of.get(`${doc_id}\u0000${line_num}`) ?? null, "row_match", t.text, t.concept_key, t.weight));
    }
  }
  return hits;
}

// --- co-occurrence and the reader's page ------------------------------------------------------

/** Lines and sections where >= 2 distinct concepts hit; a typed anchor counts as a concept. Keys "doc\0line" / "doc\0section". */
export function co_occurrence(hits) {
  const by_line = new Map();
  const by_section = new Map();
  for (const h of hits) {
    const lk = `${h.doc_id}\u0000${h.line_num}`;
    if (!by_line.has(lk)) by_line.set(lk, new Set());
    by_line.get(lk).add(h.concept_key);
    if (h.section_id) {
      const sk = `${h.doc_id}\u0000${h.section_id}`;
      if (!by_section.has(sk)) by_section.set(sk, new Set());
      by_section.get(sk).add(h.concept_key);
    }
  }
  const lines = new Set(Array.from(by_line.entries()).filter(([, v]) => v.size >= 2).map(([k]) => k));
  const sections = new Set(Array.from(by_section.entries()).filter(([, v]) => v.size >= 2).map(([k]) => k));
  return [lines, sections];
}

/** x1.3 on the page the reader is on, nothing elsewhere. */
export function current_page_boost(score, doc_id, pages_hint, factor = CURRENT_PAGE_FACTOR) {
  if (pages_hint && pages_hint.length && new Set(pages_hint).has(doc_id)) return score * factor;
  return score;
}

export function required_anchor_kind(answer_type) {
  return ANCHOR_KIND_BY_ANSWER_TYPE[String(answer_type || "text")] ?? null;
}
