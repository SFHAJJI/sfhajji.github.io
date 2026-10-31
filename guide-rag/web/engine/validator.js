// Port of guide_rag/generation/validator.py: every span and quote is checked before anything is
// shown. `validate(answer, context_lines, parsed)` returns the list of problems; empty is a pass.

import { pyListRepr, pyStrRepr } from "./_py.js";
import { attr } from "./contracts.js";
import { ValidationProblem, expected_kind, is_absence } from "./schemas.js";
import { squash } from "./text.js";

const _ISO = /^\d{4}-\d{2}-\d{2}$/;

/** Map "doc_id\0line_num" -> text, whatever shape the context came in (records, a Map, or an object). */
export function line_lookup(context_lines) {
  const out = new Map();
  if (context_lines === null || context_lines === undefined) return out;
  if (context_lines instanceof Map) {
    for (const [k, v] of context_lines) {
      const [doc, n] = Array.isArray(k) ? k : String(k).split("\u0000");
      out.set(`${doc}\u0000${Number(n)}`, squash(v));
    }
    return out;
  }
  for (const r of context_lines) out.set(`${String(attr(r, "doc_id"))}\u0000${Number(attr(r, "line_num"))}`, squash(attr(r, "text", "")));
  return out;
}

export function validate(answer, context_lines, parsed) {
  const problems = [];
  if (is_absence(answer)) {
    if (answer.answer !== null && answer.answer !== undefined) problems.push(ValidationProblem({ code: "absence_with_answer", message: "an absence carries no answer" }));
    return problems;
  }

  const kind = String(answer.kind ?? "");
  const expected = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"));
  if (kind !== expected) problems.push(ValidationProblem({ code: "shape_mismatch", message: `answer kind ${kind} but the question asks for ${expected}` }));
  const items = Array.from(answer.items || []);
  if (items.length > 0 !== Boolean(answer.answer_found)) {
    problems.push(ValidationProblem({ code: "found_flag", message: `answer_found=${answer.answer_found ? "True" : "False"} but ${items.length} item(s)` }));
  }
  if (answer.complete_answer_found && !answer.answer_found) {
    problems.push(ValidationProblem({ code: "complete_without_found", message: "complete_answer_found without answer_found" }));
  }

  const lookup = line_lookup(context_lines);
  items.forEach((item, i) => {
    const spans = Array.from(item.spans || []);
    if (!spans.length) problems.push(ValidationProblem({ code: "missing_span", message: "an item has no span", item_index: i }));
    spans.forEach((span, j) => {
      if (span.line_end < span.line_start) {
        problems.push(ValidationProblem({ code: "span_order", message: `line_end ${span.line_end} < line_start ${span.line_start}`, item_index: i, span_index: j }));
        return;
      }
      const missing = [];
      for (let n = span.line_start; n <= span.line_end; n++) if (!lookup.has(`${span.doc_id}\u0000${n}`)) missing.push(n);
      if (missing.length) {
        problems.push(ValidationProblem({ code: "span_outside_context", message: `lines ${pyListRepr(missing)} of ${span.doc_id} are not in the context`, item_index: i, span_index: j }));
        return;
      }
      const cited = [];
      for (let n = span.line_start; n <= span.line_end; n++) cited.push(lookup.get(`${span.doc_id}\u0000${n}`));
      const citedText = cited.join(" ");
      if (span.quote !== null && span.quote !== undefined && !citedText.includes(squash(span.quote))) {
        problems.push(ValidationProblem({ code: "quote_not_in_lines", message: "the quote is not in the cited lines", item_index: i, span_index: j }));
      }
      if (answer.extraction_method === "verbatim" && !(span.quote && squash(span.quote))) {
        problems.push(ValidationProblem({ code: "verbatim_without_quote", message: "a verbatim answer must carry a quote", item_index: i, span_index: j }));
      }
    });
    if (item.date !== undefined && item.date !== null && typeof item.date === "object") {
      const iso = item.date.iso;
      let ok = _ISO.test(iso);
      if (ok) {
        const [y, m, d] = iso.split("-").map(Number);
        const dt = new Date(Date.UTC(y, m - 1, d));
        ok = m >= 1 && m <= 12 && d >= 1 && dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
      }
      if (!ok) problems.push(ValidationProblem({ code: "date_not_iso", message: `date ${pyStrRepr(iso)} is not an ISO calendar date`, item_index: i }));
    }
  });
  return problems;
}
