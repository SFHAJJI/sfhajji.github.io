// Port of guide_rag/generation/absence.py: "Not in this guide" (SPEC §4), the justification built
// from the sweep, the coverage and the closest mentions, each with a why_not sentence.

import { maxBy, sortedStrings } from "./_py.js";
import { title_concepts } from "./arbiter.js";
import { as_tables, attr, concept_variants } from "./contracts.js";
import { AbsenceJustification, ConceptSearch, Mention, ParseCoverage } from "./schemas.js";
import { section_bounds } from "./scope.js";
import { concept_label } from "./text.js";

export const MAX_MENTIONS = 5;

/** The coverage JSON when brick 1 wrote one, else counts computed from the tables. */
export function coverage_of(tables, index_version = null, pipeline_version = null) {
  const t = as_tables(tables);
  if (t.parse_coverage) {
    const data = { ...t.parse_coverage };
    if (data.index_version === undefined) data.index_version = index_version || t.index_version;
    if (data.pipeline_version === undefined) data.pipeline_version = pipeline_version;
    return ParseCoverage(data);
  }
  const { line_df, toc_df, row_df, page_df } = t;
  const docs = new Set(line_df && line_df.length ? line_df.map((r) => r.doc_id) : []);
  const pages_total = page_df && page_df.length ? page_df.length : docs.size;
  return ParseCoverage({
    pages_total,
    pages_with_text: docs.size,
    lines_total: line_df ? line_df.length : 0,
    sections_total: toc_df ? toc_df.length : 0,
    tables_total: row_df && row_df.length && "table_id" in row_df[0] ? new Set(row_df.map((r) => r.table_id)).size : 0,
    cross_refs: t.cross_ref_df ? t.cross_ref_df.length : 0,
    index_version: index_version || t.index_version,
    pipeline_version,
  });
}

/** The title of the deepest section containing the line (sections nest, so the deepest level wins). */
export function innermost_title(bounds, doc_id, line_num) {
  const containing = Array.from(bounds.values()).filter((b) => b.doc_id === doc_id && b.start_line <= line_num && line_num <= b.end_line);
  if (!containing.length) return "";
  return maxBy(containing, (b) => [b.level, b.start_line]).title;
}

export function _why_not(doc_id, section_title, concept, question_concepts, variants_by_concept, reason = null) {
  const named = title_concepts(section_title, variants_by_concept).filter((c) => !question_concepts.includes(c));
  if (named.length) return `names ${concept_label(concept)} in the '${section_title}' section, which is about ${concept_label(named[0])}`;
  if (reason) return reason;
  const where = section_title ? `the '${section_title}' section` : `page ${doc_id}`;
  return `names ${concept_label(concept)} in ${where} without the other concept(s) of the question`;
}

export function build_absence(parsed, retrieval, tables, dictionary = null, { index_version = null, pipeline_version = null } = {}) {
  const t = as_tables(tables);
  const variants_by_concept = concept_variants(dictionary, parsed);
  const q_concepts = Array.from(retrieval.question_concepts);
  const searched = retrieval.sweep_concepts.map((c) => ConceptSearch({ concept: c.concept, variants: c.variants, pages_with_hits: c.pages_with_hits, line_hits: c.line_hits }));
  const hit_counts = new Map(searched.map((c) => [c.concept, c.line_hits]));
  // Every word the best candidate left uncovered is a searched concept of its own (0 hits when the
  // sweep never saw it), so the reader sees each word that was looked for.
  const terms_by_text = new Map(retrieval.terms.map((x) => [String(x.text), x]));
  for (const word of retrieval.uncovered_words) {
    const key = String((terms_by_text.get(word) || {}).concept_key || word);
    if (!hit_counts.has(key) && !hit_counts.has(word)) {
      searched.push(ConceptSearch({ concept: word, variants: [word], pages_with_hits: [], line_hits: 0 }));
      hit_counts.set(word, 0);
    }
  }

  // The reason: a vague question first, then "never mentioned", then "mentioned but off topic".
  const ambiguity = attr(parsed, "ambiguity_reason");
  let reason;
  if (ambiguity) reason = "ambiguous_question";
  else if (!searched.length || Array.from(hit_counts.values()).some((n) => n === 0)) reason = "concept_not_found";
  else reason = "concept_found_but_off_topic";

  // Closest mentions: the non-primary candidates first (they carry the arbiter's sentence), then the
  // sweep rows not already shown.
  const bounds = section_bounds(t.toc_df);
  let mentions = [];
  const seen = new Set();
  for (const c of retrieval.candidates) {
    if (c.role === "primary") continue;
    const key = `${c.anchor.doc_id}\u0000${c.anchor.line_start}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const concept = c.matched_concepts.length ? c.matched_concepts[0] : c.matched_keywords.length ? c.matched_keywords[0] : "the term";
    mentions.push(
      Mention({
        doc_id: c.anchor.doc_id,
        line_num: c.anchor.line_start,
        snippet: c.snippet,
        why_not_an_answer: _why_not(c.anchor.doc_id, c.section_title, concept, q_concepts, variants_by_concept, c.reason),
      }),
    );
  }
  for (const r of retrieval.sweep_rows) {
    if (mentions.length >= MAX_MENTIONS) break;
    const key = `${r.doc_id}\u0000${r.line_num}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const title = innermost_title(bounds, r.doc_id, r.line_num);
    mentions.push(Mention({ doc_id: r.doc_id, line_num: r.line_num, snippet: r.snippet, why_not_an_answer: _why_not(r.doc_id, title, r.concept, q_concepts, variants_by_concept) }));
  }
  mentions = mentions.slice(0, MAX_MENTIONS);

  let suggestion = attr(parsed, "proposed_default") || attr(parsed, "suggested_clarification");
  if (!suggestion) {
    const missing = Array.from(hit_counts.entries()).filter(([, n]) => n === 0).map(([c]) => c);
    const present = Array.from(hit_counts.entries()).filter(([, n]) => n > 0).map(([c]) => c);
    if (missing.length && present.length) {
      suggestion = `The guide never mentions ${missing.map(concept_label).join(", ")}; it does cover ${present.map(concept_label).join(", ")}: ask about that.`;
    } else if (missing.length) {
      suggestion = `The guide never mentions ${missing.map(concept_label).join(", ")}; try another wording or another topic of the guide.`;
    } else if (mentions.length) {
      const pages = sortedStrings(mentions.map((m) => m.doc_id));
      suggestion = `The terms appear on ${pages.join(", ")} but in sections about something else; ask about those sections directly.`;
    } else {
      suggestion = "Try another wording or another topic of the guide.";
    }
  }

  return AbsenceJustification({
    reason,
    searched_concepts: searched,
    closest_mentions: mentions,
    parse_coverage: coverage_of(t, index_version, pipeline_version),
    suggestion,
    suggested_clarification: attr(parsed, "suggested_clarification"),
  });
}
