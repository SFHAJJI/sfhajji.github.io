// Port of guide_rag/retrieval/sweep.py: the exhaustive absence sweep (SPEC §3), every variant of
// every concept of the question as a whole-word regex over EVERY line of EVERY page. Not top-k.

import { _s, sortedBy, sortedStrings } from "./_py.js";
import { as_tables, concept_variants, question_terms } from "./contracts.js";
import { fold, snippet_of, variant_regex } from "./text.js";

export function SweepRow(concept, variant, doc_id, line_num, snippet) {
  return { concept, variant, doc_id, line_num, snippet };
}

export function ConceptSweep(concept, variants, pages_with_hits = [], line_hits = 0) {
  return { concept, variants, pages_with_hits, line_hits };
}

export function SweepResult(rows, concepts, pages_scanned, lines_scanned) {
  return { rows, concepts, pages_scanned, lines_scanned, rows_for: (concept) => rows.filter((r) => r.concept === concept) };
}

/**
 * concept -> variants to sweep: the question's concepts (all their dictionary variants) plus every
 * direct keyword without a concept, as a concept of its own. Insertion order is Python's dict order.
 */
export function question_concept_variants(parsed, dictionary = null) {
  const by_concept = concept_variants(dictionary, parsed);
  const terms = question_terms(parsed, by_concept);
  const out = new Map();
  for (const t of terms) {
    if (t.is_regex) continue;
    const variants = t.concept ? Array.from(by_concept[t.concept_key] || []) : [];
    if (!variants.includes(t.text)) variants.push(t.text);
    if (!out.has(t.concept_key)) out.set(t.concept_key, []);
    const bucket = out.get(t.concept_key);
    for (const v of variants) if (!bucket.includes(v)) bucket.push(v);
  }
  return out;
}

/** Every page, every line, every variant. Rows ordered by concept, page, line, variant. */
export function sweep(parsed, tables, dictionary = null) {
  const t = as_tables(tables);
  const by_concept = question_concept_variants(parsed, dictionary);
  const line_df = t.line_df;
  const records = !line_df || line_df.length === 0 ? [] : sortedBy(line_df, (r) => [r.doc_id, r.line_num]);
  const folded = records.map((r) => [String(r.doc_id), Number(r.line_num), _s(r.text)]);
  const rows = [];
  const concepts = [];
  for (const [concept, variants] of by_concept) {
    const patterns = variants.map((v) => [v, variant_regex(v)]);
    const pages = new Set();
    let n = 0;
    for (const [doc_id, line_num, text] of folded) {
      const ftext = fold(text);
      for (const [v, rx] of patterns) {
        if (rx.test(ftext)) {
          rows.push(SweepRow(concept, v, doc_id, line_num, snippet_of(text)));
          pages.add(doc_id);
          n += 1;
        }
      }
    }
    concepts.push(ConceptSweep(concept, Array.from(variants), sortedStrings(pages), n));
  }
  return SweepResult(rows, concepts, new Set(folded.map(([d]) => d)).size, folded.length);
}
