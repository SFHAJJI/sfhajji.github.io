// Port of guide_rag/generation/meta.py: the `_meta` block of SPEC §4, what ran, what was skipped
// and why, which model, which prompt.

import { pyRound } from "./_py.js";
import { attr, hints, plan_activations } from "./contracts.js";
import { GenerationMeta } from "./schemas.js";

export function chunk_strategy_of(parsed) {
  const [, , answer_context] = hints(parsed);
  const context = { line: "the hit lines", paragraph: "±3 lines within the section", section: "the whole section" };
  return `line as the unit; anchor = hit lines grouped by runs; context = ${context[answer_context] ?? answer_context} (answer_context=${answer_context})`;
}

export function build_meta(
  parsed,
  plan,
  retrieval,
  { index_version = null, pipeline_version, model_used = "no model", prompt_version = null, fragments_applied = null, iterations = 1, validator_report = null, timings_ms = null },
) {
  const timings = {};
  for (const [k, v] of Object.entries(timings_ms || {})) timings[k] = pyRound(Number(v), 3);
  return GenerationMeta({
    question_id: String(attr(parsed, "question_id", "") || ""),
    index_version,
    pipeline_version,
    methods_used: retrieval ? Array.from(retrieval.methods_used) : [],
    methods_skipped: retrieval ? { ...retrieval.methods_skipped } : {},
    activations: plan_activations(plan),
    chunk_strategy: chunk_strategy_of(parsed),
    model_used,
    prompt_version,
    fragments_applied: Array.from(fragments_applied || []),
    iterations,
    validator_report: { ...(validator_report || {}) },
    timings_ms: timings,
  });
}
