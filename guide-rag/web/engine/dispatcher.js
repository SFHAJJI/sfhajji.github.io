// Port of guide_rag/question/dispatcher.py: one `ExecutionPlan` per parsed question, every flag
// with a reason. SPEC §0 rule 7: same question, same route.

import { pyListRepr } from "./_py.js";
import { fold } from "./normalize.js";

export const MIN_TOC_SECTIONS = 3;
export const EMBEDDINGS_OFF_REASON = "no vocabulary mismatch expected beyond the dictionary; keywords prove absence";

export function Activation(on, reason) {
  return { on, reason };
}

const FLAGS = [
  "use_keywords",
  "use_toc",
  "use_row_level",
  "use_embeddings",
  "use_llm_arbiter",
  "use_llm_generation",
  "sweep_for_absence",
  "current_page_boost",
];

/** The plan object; `activations()` is a method, as on the pydantic model (a re-sync concern of contracts.js). */
export function ExecutionPlan(fields) {
  const plan = {
    question_id: fields.question_id,
    use_keywords: fields.use_keywords,
    use_toc: fields.use_toc,
    use_row_level: fields.use_row_level,
    use_embeddings: fields.use_embeddings,
    use_llm_arbiter: fields.use_llm_arbiter,
    use_llm_generation: fields.use_llm_generation,
    sweep_for_absence: fields.sweep_for_absence,
    current_page_boost: fields.current_page_boost,
    answer_context: fields.answer_context,
    answer_context_reason: fields.answer_context_reason,
    chunk_strategy: fields.chunk_strategy,
    chunk_strategy_reason: fields.chunk_strategy_reason,
  };
  Object.defineProperty(plan, "activations", { value: () => activations(plan), enumerable: false });
  Object.defineProperty(plan, "methods_planned", { get: () => methods_planned(plan), enumerable: false });
  return plan;
}

/** The `_meta.activations` block: {flag: {on, reason}}. */
export function activations(plan) {
  const out = {};
  for (const name of FLAGS) {
    const value = plan[name];
    if (value && typeof value === "object" && "on" in value) out[name] = { on: value.on, reason: value.reason };
  }
  return out;
}

export function methods_planned(plan) {
  return Object.entries(activations(plan))
    .filter(([, a]) => a.on)
    .map(([name]) => name);
}

/** A keyword that is also a column header of some table, else null. */
export function _named_table_column(parsed, row_df) {
  if (!row_df || row_df.length === 0 || !("column_headers" in row_df[0])) return null;
  const headers = new Set();
  for (const value of row_df.map((r) => r.column_headers)) {
    let parts;
    if (typeof value === "string") parts = value.split("|");
    else if (value && typeof value[Symbol.iterator] === "function") parts = Array.from(value);
    else parts = [];
    for (const p of parts) if (String(p).trim()) headers.add(fold(String(p).trim()));
  }
  for (const keyword of parsed.keywords) {
    if (keyword.is_regex) continue;
    if (headers.has(fold(keyword.text))) return keyword.text;
  }
  return null;
}

/** Decide every retrieval and generation method from the parsed question alone. */
export function dispatch(parsed, { toc_df, llm_available = false, row_df = null }) {
  const n_sections = toc_df ? toc_df.length : 0;
  const shape = parsed.answer_shape;
  const atype = parsed.answer_type;

  const use_toc = n_sections >= MIN_TOC_SECTIONS;
  const column = _named_table_column(parsed, row_df);
  let row_level;
  if (atype === "amount" || atype === "date") row_level = Activation(true, `answer_type=${atype}: tables carry typed values`);
  else if (column !== null) row_level = Activation(true, `the question names the table column '${column}'`);
  else row_level = Activation(false, `answer_type=${atype} and no table column named`);

  let context, context_reason, chunk, chunk_reason;
  if (shape === "listing") {
    context = "section";
    context_reason = "listing: the whole section is the answer";
    [chunk, chunk_reason] = ["combined", "listing: the section's lines are read together, one item per line"];
  } else if (["amount", "date", "boolean", "phone", "url", "duration"].includes(atype)) {
    [context, context_reason] = ["line", `${atype}: a typed value sits on one line`];
    [chunk, chunk_reason] = ["sequential", "single typed value: candidates are tried one by one, best first"];
  } else {
    [context, context_reason] = ["paragraph", `single ${atype}: the paragraph around the anchor`];
    [chunk, chunk_reason] = ["sequential", "single text answer: candidates are tried one by one, best first"];
  }

  const pages = parsed.structural_hints.pages_hint;
  return ExecutionPlan({
    question_id: parsed.question_id,
    use_keywords: Activation(true, "always: keyword detectors are deterministic and prove absence"),
    use_toc: Activation(
      use_toc,
      use_toc
        ? `toc_df has ${n_sections} sections (>= ${MIN_TOC_SECTIONS}): headings are a first-class signal`
        : `toc_df has ${n_sections} sections (< ${MIN_TOC_SECTIONS}): too few headings to route by`,
    ),
    use_row_level: row_level,
    use_embeddings: Activation(false, EMBEDDINGS_OFF_REASON),
    use_llm_arbiter: Activation(llm_available, llm_available ? "a model key is configured" : "no model key configured"),
    use_llm_generation: Activation(llm_available, llm_available ? "a model key is configured" : "no model key configured"),
    sweep_for_absence: Activation(true, "always: the exhaustive sweep is the evidence of absence"),
    current_page_boost: Activation(
      Boolean(pages && pages.length),
      pages && pages.length ? `pages_hint=${pyListRepr(pages)}: the reader's page gets x1.3` : "no pages_hint: no page to boost",
    ),
    answer_context: context,
    answer_context_reason: context_reason,
    chunk_strategy: chunk,
    chunk_strategy_reason: chunk_reason,
  });
}
