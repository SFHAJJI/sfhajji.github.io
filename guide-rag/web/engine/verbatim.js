// Port of guide_rag/generation/verbatim.py: the no-model generator of SPEC §4. The primary
// candidate's anchor lines become the item(s), verbatim; typed values come from the regex captures
// with the line as their span.

import { maxBy, pyG, pyStr, sortedStrings } from "./_py.js";
import { as_tables, attr, question_terms } from "./contracts.js";
import { line_records } from "./detectors.js";
import { primaries as primaries_of } from "./result.js";
import { boundsKey, is_whole_section, section_bounds } from "./scope.js";
import { ANSWER_CLASSES, Amount, AmountItem, BooleanItem, ConflictingEvidence, ContextBlock, DateItem, DateValue, Span, TextItem, expected_kind } from "./schemas.js";
import { phrase_in, stems } from "./text.js";

export const MAX_LIST_ITEMS = 30;
export const PARTIAL_CONFIDENCE_CAP = 0.6;
export const NEGATIONS = new Set(["pas", "ne", "non", "aucun", "aucune", "jamais", "interdit", "interdite", "not", "no", "never", "nicht", "kein", "keine", "nie"]);
export const CAPTURE_KINDS = { amount: new Set(["amount", "duration"]), date: new Set(["date"]) };

export function context_blocks(candidates) {
  return candidates.map((c) =>
    ContextBlock({
      candidate_id: c.candidate_id,
      doc_id: c.context.doc_id,
      section_id: c.context.section_id,
      section_title: c.section_title,
      breadcrumb: c.breadcrumb,
      line_start: c.context.line_start,
      line_end: c.context.line_end,
      url_anchor: c.url_anchor,
      role: c.role,
    }),
  );
}

/** The typed not-answered answer: the right class, no item, both booleans false. */
export function not_answered(kind, retrieval, caveats) {
  const prim = retrieval ? primaries_of(retrieval) : [];
  return ANSWER_CLASSES[kind]({
    items: [],
    extraction_method: "na",
    confidence: 0.0,
    caveats: Array.from(caveats),
    answer_found: false,
    complete_answer_found: false,
    context_structured: retrieval ? context_blocks(prim) : [],
    keywords_found: sortedStrings(prim.flatMap((c) => c.matched_keywords)),
  });
}

export function _lines(lines, doc_id, start, end) {
  return lines.filter((l) => l.doc_id === doc_id && start <= l.line_num && l.line_num <= end);
}

export function _fmt_amount(cap) {
  const v = pyG(cap.value);
  return [v, cap.currency || "", cap.unit || ""].filter((x) => x).join(" ");
}

/** Typed items from the first primary's captures; other pages with other values are conflicts. */
export function _typed_items(primaries, kind, lines) {
  const wanted = CAPTURE_KINDS[kind];
  const items = [];
  const conflicts = [];
  const caveats = [];
  const seen_values = new Set();

  const values_of = (c) => {
    const out = [];
    for (const cap of c.captures) {
      if (wanted.has(cap.kind)) out.push([kind === "date" ? cap.iso : _fmt_amount(cap), cap]);
    }
    return out;
  };

  const item_of = (c, cap) => {
    const line = _lines(lines, c.anchor.doc_id, cap.line_num, cap.line_num)[0] ?? null;
    const span = Span({ doc_id: c.anchor.doc_id, line_start: cap.line_num, line_end: cap.line_num, quote: line ? line.text : null });
    if (kind === "date") return DateItem({ date: DateValue({ iso: cap.iso, original: cap.original }), spans: [span] });
    return AmountItem({ amount: Amount({ value: cap.value, currency: cap.currency ?? null, unit: cap.unit ?? null }), spans: [span] });
  };

  const first = primaries[0];
  const first_values = values_of(first);
  for (const [key, cap] of first_values) {
    if (!seen_values.has(key)) {
      seen_values.add(key);
      items.push(item_of(first, cap));
    }
  }
  if (!first_values.length) caveats.push(`No ${kind} on the primary lines ${first.candidate_id}; nothing typed could be extracted.`);
  const first_keys = new Set(first_values.map(([k]) => k));
  for (const other of primaries.slice(1)) {
    const vals = values_of(other);
    if (!vals.length) continue;
    const keys = new Set(vals.map(([k]) => k));
    const sameKeys = keys.size === first_keys.size && Array.from(keys).every((k) => first_keys.has(k));
    if (other.anchor.doc_id !== first.anchor.doc_id && !sameKeys) {
      conflicts.push(
        ConflictingEvidence({
          candidate_ids: [first.candidate_id, other.candidate_id],
          values: [sortedStrings(first_keys).join(", ") || "none", sortedStrings(keys).join(", ")],
          note: `${first.breadcrumb || first.anchor.doc_id} and ${other.breadcrumb || other.anchor.doc_id} carry different values.`,
        }),
      );
      caveats.push(`Conflicting value on ${other.anchor.doc_id} (${other.candidate_id}): ${sortedStrings(keys).join(", ")}.`);
    } else if (other.anchor.doc_id === first.anchor.doc_id) {
      for (const [key, cap] of vals) {
        if (!seen_values.has(key)) {
          seen_values.add(key);
          items.push(item_of(other, cap));
        }
      }
    }
  }
  return [items, conflicts, caveats];
}

/**
 * One item per list item / matching line of each primary's context (the section for listings);
 * when the section has child sections, their headings are items too (the steps of a procedure).
 */
export function _list_items(primaries, lines, parsed, bounds = null) {
  const term_stems = question_terms(parsed).filter((t) => !t.is_regex && stems(t.text).length).map((t) => stems(t.text));
  const items = [];
  const seen = new Set();
  for (const c of primaries) {
    const ctx = _lines(lines, c.context.doc_id, c.context.line_start, c.context.line_end);
    let picked = ctx.filter((l) => !l.is_heading && (["li", "td", "dd"].includes(l.element) || term_stems.some((ps) => phrase_in(ps, l.stems))));
    const b = bounds ? bounds.get(boundsKey(c.context.doc_id, c.context.section_id || "")) ?? null : null;
    if (b !== null && b.own_end < b.end_line) {
      const children = Array.from(bounds.values()).filter((x) => x.doc_id === b.doc_id && b.start_line < x.start_line && x.start_line <= b.end_line && x.level === b.level + 1);
      children.sort((x, y) => x.start_line - y.start_line);
      picked = picked.concat(children.flatMap((x) => _lines(lines, x.doc_id, x.start_line, x.start_line)));
    }
    if (!picked.length) picked = _lines(lines, c.anchor.doc_id, c.anchor.line_start, c.anchor.line_end);
    for (const l of picked) {
      const k = `${l.doc_id}\u0000${l.line_num}`;
      if (seen.has(k) || items.length >= MAX_LIST_ITEMS) continue;
      seen.add(k);
      items.push(TextItem({ text: l.text, spans: [Span({ doc_id: l.doc_id, line_start: l.line_num, line_end: l.line_num, quote: l.text })] }));
    }
  }
  return items;
}

export function _negated(text) {
  return stems(text).some((tok) => NEGATIONS.has(tok)) || text.toLowerCase().split(/\s+/).filter(Boolean).some((tok) => NEGATIONS.has(tok));
}

export function generate_verbatim(parsed, retrieval, tables) {
  const kind = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"));
  const primaries = primaries_of(retrieval);
  if (!primaries.length) return not_answered(kind, retrieval, [retrieval.not_found_reason || "no primary candidate"]);
  const t = as_tables(tables);
  const lines = line_records(t.line_df, new Set(primaries.map((c) => c.anchor.doc_id)));
  const bounds = section_bounds(t.toc_df);
  const first = primaries[0];
  let caveats = [];
  let conflicts = [];
  let extraction = "verbatim";
  let items = [];
  let complete;
  const firstBounds = () => bounds.get(boundsKey(first.context.doc_id, first.context.section_id || "")) ?? null;

  if (kind === "list") {
    items = _list_items(primaries, lines, parsed, bounds);
    complete = is_whole_section([first.context.line_start, first.context.line_end], firstBounds());
  } else if (kind === "amount" || kind === "date") {
    [items, conflicts, caveats] = _typed_items(primaries, kind, lines);
    extraction = "computed"; // the value is normalised (1 500 -> 1500.0, 15 janvier 2025 -> ISO)
    complete = items.length > 0;
  } else if (kind === "boolean") {
    // The item quotes the one sentence that answers: the anchor line carrying most question terms.
    const anchor_lines = _lines(lines, first.anchor.doc_id, first.anchor.line_start, first.anchor.line_end);
    const term_stems = question_terms(parsed).filter((x) => !x.is_regex && stems(x.text).length).map((x) => stems(x.text));
    const best = maxBy(anchor_lines, (l) => [term_stems.filter((ps) => phrase_in(ps, l.stems)).length, -l.line_num]);
    const text = best.text;
    const value = !_negated(text);
    items = [BooleanItem({ boolean: value, spans: [Span({ doc_id: best.doc_id, line_start: best.line_num, line_end: best.line_num, quote: text })] })];
    extraction = "inferred";
    caveats.push("No model: the boolean is a negation heuristic over the quoted lines; read the quote.");
    for (const other of primaries.slice(1)) {
      const o_lines = _lines(lines, other.anchor.doc_id, other.anchor.line_start, other.anchor.line_end);
      const o_value = !_negated(o_lines.map((l) => l.text).join(" "));
      if (other.anchor.doc_id !== first.anchor.doc_id && o_value !== value) {
        conflicts.push(
          ConflictingEvidence({
            candidate_ids: [first.candidate_id, other.candidate_id],
            values: [pyStr(value), pyStr(o_value)],
            note: `${first.breadcrumb} and ${other.breadcrumb} read differently.`,
          }),
        );
      }
    }
    complete = items.length > 0;
  } else {
    // A section context (a procedure) quotes the section's lines; otherwise the anchor lines.
    // Leading heading lines are left out of the quote: the breadcrumb already names them.
    let span_lines;
    if (retrieval.answer_context_used === "section") {
      span_lines = _lines(lines, first.context.doc_id, first.context.line_start, first.context.line_end);
      while (span_lines.length > 1 && span_lines[0].is_heading && span_lines[0].line_num < first.anchor.line_start) span_lines = span_lines.slice(1);
    } else {
      span_lines = _lines(lines, first.anchor.doc_id, first.anchor.line_start, first.anchor.line_end);
    }
    const text = span_lines.map((l) => l.text).join(" ");
    items = [TextItem({ text, spans: [Span({ doc_id: first.anchor.doc_id, line_start: span_lines[0].line_num, line_end: span_lines[span_lines.length - 1].line_num, quote: text })] })];
    for (const other of primaries.slice(1)) {
      if (other.anchor.doc_id !== first.anchor.doc_id) caveats.push(`Also found on ${other.anchor.doc_id}: ${other.breadcrumb} (${other.candidate_id}).`);
    }
    complete = is_whole_section([first.context.line_start, first.context.line_end], firstBounds());
  }

  if (!complete && items.length) {
    const b = firstBounds();
    const where = first.breadcrumb || first.section_title ? `'${first.breadcrumb || first.section_title}'` : first.anchor.doc_id;
    const span_note = b ? ` (the section spans lines ${b.start_line}-${b.end_line})` : "";
    caveats.push(`The context covers lines ${first.context.line_start}-${first.context.line_end} of ${where}${span_note}, not the whole section.`);
  }

  // A partial answer never claims more than 0.6, whatever the retrieval margin said.
  const confidence = items.length && complete ? retrieval.confidence : Math.min(retrieval.confidence, PARTIAL_CONFIDENCE_CAP);
  return ANSWER_CLASSES[kind]({
    items,
    extraction_method: items.length ? extraction : "na",
    confidence,
    caveats,
    answer_found: items.length > 0,
    complete_answer_found: items.length > 0 && complete,
    context_structured: context_blocks(primaries),
    keywords_found: sortedStrings(primaries.flatMap((c) => c.matched_keywords)),
    conflicting_evidence: conflicts,
  });
}
