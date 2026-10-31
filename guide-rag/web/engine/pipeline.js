// Port of guide_rag/generation/pipeline.py: `answer_question` = retrieve -> verbatim (or the
// model) -> validate (one retry with discovered keywords, then a typed not-answered) -> absence when
// nothing was found. `replay` re-runs a trace. The model path is async (fetch), so the pipeline is
// async too; without a model nothing awaits.

import { sortedStrings } from "./_py.js";
import { ExecutionPlan, Keyword, ParsedQuestion, as_tables, attr, concept_variants, plan_activation, plan_activations, question_terms } from "./contracts.js";
import { line_records } from "./detectors.js";
import { primaries, retrieve } from "./result.js";
import { contains_keyword, fold } from "./text.js";
import { build_absence } from "./absence.js";
import { build_meta } from "./meta.js";
import { GenerationResult, Trace, expected_kind, is_absence } from "./schemas.js";
import { validate } from "./validator.js";
import { generate_verbatim, not_answered } from "./verbatim.js";

export const PIPELINE_VERSION = "guide-rag/0.1";
export const MAX_DISCOVERED = 5;

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

/** A plain object copy of a model, a mapping or a namespace (JSON round trip). */
export function _dump(obj) {
  if (obj === null || obj === undefined) return {};
  return JSON.parse(JSON.stringify(obj));
}

/** The duck-typed question as the contract model, so it can be copied with more keywords and traced. */
export function to_parsed(parsed) {
  const data = _dump(parsed);
  if (data.question_id === undefined) data.question_id = String(attr(parsed, "question_id", "") || "");
  if (data.original_question === undefined) data.original_question = String(attr(parsed, "original_question", "") || "");
  if (data.corrected_question === undefined) data.corrected_question = String(attr(parsed, "corrected_question", data.original_question) || "");
  return ParsedQuestion(data);
}

export function to_plan(plan) {
  if (plan && plan.activations && typeof plan.activations !== "function" && Object.keys(plan).length === 1) return ExecutionPlan(plan);
  return ExecutionPlan({ activations: plan_activations(plan) });
}

/**
 * Keywords for the retry: what the model proposed, plus dictionary variants of the question's
 * concepts that occur in the primaries' context but are not yet in the question.
 */
export function discovered_keywords(answer, parsed, retrieval, tables, dictionary) {
  const have = new Set(question_terms(parsed).map((t) => fold(t.text)));
  const found = [];
  for (const text of answer !== null && answer !== undefined ? answer.llm_discovered_keywords || [] : []) {
    if (!have.has(fold(text))) {
      have.add(fold(text));
      found.push(Keyword({ text, weight: 0.6, source: "expert_dictionary", concept: null }));
    }
  }
  const by_concept = concept_variants(dictionary, parsed);
  const q_concepts = new Set(retrieval.question_concepts);
  const t = as_tables(tables);
  const shown = retrieval.candidates.filter((c) => c.role !== "discarded");
  const lines = line_records(t.line_df, new Set(shown.map((c) => c.context.doc_id)));
  const texts = [];
  for (const c of shown) for (const l of lines) if (l.doc_id === c.context.doc_id && c.context.line_start <= l.line_num && l.line_num <= c.context.line_end) texts.push(l.text);
  for (const concept of sortedStrings(q_concepts)) {
    for (const v of by_concept[concept] || []) {
      if (have.has(fold(v)) || found.length >= MAX_DISCOVERED) continue;
      if (texts.some((x) => contains_keyword(x, v))) {
        have.add(fold(v));
        found.push(Keyword({ text: v, weight: 0.6, source: "expert_dictionary", concept }));
      }
    }
  }
  return found.slice(0, MAX_DISCOVERED);
}

export async function answer_question(parsed, plan, tables, dictionary = null, { llm_client = null, index_version = null } = {}) {
  const timings = {};
  const t = as_tables(tables);
  index_version = index_version || t.index_version;
  const pq = to_parsed(parsed);
  const plan_model = to_plan(plan);
  const [use_llm] = plan_activation(plan_model, "use_llm_generation");
  let model_used = "no model";
  let prompt_version = null;
  let fragments = [];

  const generate = async (retr) => {
    if (use_llm && llm_client !== null && primaries(retr).length) {
      const { generate_with_llm } = await import("./llm.js"); // imported here so the no-model path never needs it
      const [answer, info] = await generate_with_llm(pq, retr, t, llm_client);
      model_used = info.model_used;
      prompt_version = info.prompt_version;
      fragments = info.fragments_applied;
      return answer;
    }
    return generate_verbatim(pq, retr, t);
  };

  const t0 = now();
  let retrieval = retrieve(pq, plan_model, t, dictionary);
  timings.retrieval = now() - t0;
  const t1 = now();
  let answer = await generate(retrieval);
  timings.generation = now() - t1;
  const t2 = now();
  const report = { iteration_1: validate(answer, t.line_df, pq) };
  let iterations = 1;
  if (report.iteration_1.length) {
    // One retry with the discovered keywords; then the typed not-answered. What fails is not shipped.
    const extra = discovered_keywords(answer, pq, retrieval, t, dictionary);
    const pq2 = extra.length ? { ...pq, keywords: pq.keywords.concat(extra) } : pq;
    retrieval = retrieve(pq2, plan_model, t, dictionary);
    answer = await generate(retrieval);
    report.iteration_2 = validate(answer, t.line_df, pq);
    iterations = 2;
    if (report.iteration_2.length) {
      const kind = expected_kind(pq.answer_shape, pq.answer_type);
      answer = not_answered(kind, retrieval, ["Rejected by the validator: " + report.iteration_2.map((p) => p.message).join("; ")]);
    }
  }
  timings.validation = now() - t2;

  let final = answer;
  if (retrieval.not_found && !answer.items.length) {
    const t3 = now();
    final = build_absence(pq, retrieval, t, dictionary, { index_version, pipeline_version: PIPELINE_VERSION });
    timings.absence = now() - t3;
  }
  timings.total = now() - t0;

  const meta = build_meta(pq, plan_model, retrieval, {
    index_version,
    pipeline_version: PIPELINE_VERSION,
    model_used,
    prompt_version,
    fragments_applied: fragments,
    iterations,
    validator_report: report,
    timings_ms: timings,
  });
  return GenerationResult({ answer: final, meta, trace: Trace({ parsed: pq, plan: plan_model, retrieval }) });
}

/** Re-run a saved GenerationResult (its JSON) and record whether the same candidates and spans came back. */
export async function replay(trace_json, tables, dictionary = null, llm_client = null) {
  const data = typeof trace_json === "string" ? JSON.parse(trace_json) : trace_json;
  const trace = data.trace || {};
  const parsed = ParsedQuestion(trace.parsed);
  const plan = ExecutionPlan(trace.plan);
  const index_version = (data.meta || {}).index_version ?? null;
  const result = await answer_question(parsed, plan, tables, dictionary, { llm_client, index_version });
  const old_ids = ((trace.retrieval || {}).candidates || []).map((c) => c.candidate_id);
  const new_ids = result.trace ? result.trace.retrieval.candidates.map((c) => c.candidate_id) : [];
  const old_answer = data.answer || {};
  const old_spans = (old_answer.items || []).flatMap((it) => it.spans || []);
  const new_spans = is_absence(result.answer) ? [] : result.answer.items.flatMap((it) => it.spans);
  result.meta.replay = {
    source_question_id: parsed.question_id,
    candidates_identical: JSON.stringify(old_ids) === JSON.stringify(new_ids),
    spans_identical: JSON.stringify(old_spans) === JSON.stringify(new_spans),
    index_version_identical: index_version === result.meta.index_version,
  };
  return result;
}
