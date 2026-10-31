// Port of guide_rag/generation/schemas.py: the typed answer of SPEC §4 as plain-object builders
// (pydantic models in Python). Every item carries spans; the two booleans sit on every answer.

export function Span({ doc_id, line_start, line_end, quote = null }) {
  return { doc_id, line_start, line_end, quote };
}

export function Amount({ value, currency = null, unit = null }) {
  return { value, currency, unit };
}

export function DateValue({ iso, original }) {
  return { iso, original };
}

export function TextItem({ text, spans = [] }) {
  return { text, spans };
}

export function AmountItem({ amount, spans = [] }) {
  return { amount, spans };
}

export function DateItem({ date, spans = [] }) {
  return { date, spans };
}

export function BooleanItem({ boolean, spans = [] }) {
  return { boolean, spans };
}

/** Where an answer comes from: the structural address of a primary candidate. */
export function ContextBlock(f) {
  return {
    candidate_id: f.candidate_id,
    doc_id: f.doc_id,
    section_id: f.section_id ?? null,
    section_title: f.section_title ?? "",
    breadcrumb: f.breadcrumb ?? "",
    line_start: f.line_start,
    line_end: f.line_end,
    url_anchor: f.url_anchor ?? null,
    role: f.role ?? "primary",
  };
}

export function ConflictingEvidence({ candidate_ids, values, note }) {
  return { candidate_ids, values, note };
}

/** The AnswerBase family: `kind` is the discriminator (text, list, amount, date, boolean). */
export function AnswerBase(kind, f = {}) {
  if (!(kind in ANSWER_CLASSES)) throw new Error(`unknown answer kind ${kind}`);
  return {
    extraction_method: f.extraction_method ?? "na",
    confidence: f.confidence ?? 0.0,
    caveats: f.caveats ?? [],
    answer_found: f.answer_found ?? false,
    complete_answer_found: f.complete_answer_found ?? false,
    context_structured: f.context_structured ?? [],
    keywords_found: f.keywords_found ?? [],
    llm_discovered_keywords: f.llm_discovered_keywords ?? [],
    conflicting_evidence: f.conflicting_evidence ?? [],
    suggested_clarification: f.suggested_clarification ?? null,
    kind,
    items: f.items ?? [],
  };
}

export function TextAnswer(f) {
  return AnswerBase("text", f);
}
export function ListAnswer(f) {
  return AnswerBase("list", f);
}
export function AmountAnswer(f) {
  return AnswerBase("amount", f);
}
export function DateAnswer(f) {
  return AnswerBase("date", f);
}
export function BooleanAnswer(f) {
  return AnswerBase("boolean", f);
}

export const ANSWER_CLASSES = { text: TextAnswer, list: ListAnswer, amount: AmountAnswer, date: DateAnswer, boolean: BooleanAnswer };

export function ActivationOut({ on, reason }) {
  return { on, reason };
}

export function ConceptSearch({ concept, variants, pages_with_hits, line_hits }) {
  return { concept, variants, pages_with_hits, line_hits };
}

export function Mention({ doc_id, line_num, snippet, why_not_an_answer }) {
  return { doc_id, line_num, snippet, why_not_an_answer };
}

export function ParseCoverage(data = {}) {
  return {
    pages_total: data.pages_total ?? 0,
    pages_with_text: data.pages_with_text ?? 0,
    lines_total: data.lines_total ?? 0,
    sections_total: data.sections_total ?? 0,
    tables_total: data.tables_total ?? 0,
    cross_refs: data.cross_refs ?? 0,
    fetched_at: data.fetched_at ?? null,
    index_version: data.index_version ?? null,
    pipeline_version: data.pipeline_version ?? null,
    ...Object.fromEntries(Object.entries(data).filter(([k]) => !["pages_total", "pages_with_text", "lines_total", "sections_total", "tables_total", "cross_refs", "fetched_at", "index_version", "pipeline_version"].includes(k))),
  };
}

/** "Not in this guide" with its four kinds of evidence. */
export function AbsenceJustification(f) {
  return {
    kind: "absence",
    answer: null,
    reason: f.reason,
    searched_concepts: f.searched_concepts ?? [],
    closest_mentions: f.closest_mentions ?? [],
    parse_coverage: f.parse_coverage ?? ParseCoverage(),
    suggestion: f.suggestion ?? null,
    suggested_clarification: f.suggested_clarification ?? null,
    answer_found: false,
    complete_answer_found: false,
  };
}

export function is_absence(answer) {
  return Boolean(answer) && answer.kind === "absence";
}

/** The answer class a question calls for: listing wins, then the typed kinds, then text. */
export function expected_kind(answer_shape, answer_type) {
  if (answer_shape === "listing") return "list";
  const t = answer_type || "text";
  if (t === "amount" || t === "duration") return "amount";
  if (t === "date" || t === "boolean") return t;
  return "text";
}

export function ValidationProblem({ code, message, item_index = null, span_index = null }) {
  return { code, message, item_index, span_index };
}

/** The `_meta` block of SPEC §4. */
export function GenerationMeta(f) {
  return {
    question_id: f.question_id,
    index_version: f.index_version ?? null,
    pipeline_version: f.pipeline_version,
    methods_used: f.methods_used ?? [],
    methods_skipped: f.methods_skipped ?? {},
    activations: f.activations ?? {},
    chunk_strategy: f.chunk_strategy ?? "",
    model_used: f.model_used ?? "no model",
    prompt_version: f.prompt_version ?? null,
    fragments_applied: f.fragments_applied ?? [],
    iterations: f.iterations ?? 1,
    validator_report: f.validator_report ?? {},
    timings_ms: f.timings_ms ?? {},
    replay: f.replay ?? null,
  };
}

/** What replay needs: the parsed question and the plan as they were, plus the retrieval. */
export function Trace({ parsed, plan, retrieval }) {
  return { parsed, plan, retrieval };
}

export function GenerationResult({ answer, meta, trace = null }) {
  return { answer, meta, trace };
}

/** The JSON of the result without the timings: identical across runs of the same question. */
export function stable_json(result) {
  const { timings_ms, replay, ...meta } = result.meta;
  return JSON.stringify({ answer: result.answer, meta, trace: result.trace });
}
