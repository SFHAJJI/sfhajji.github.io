// Port of guide_rag/generation/llm.py: the optional model path of SPEC §4, an OpenAI-compatible
// endpoint, temperature 0, JSON-schema structured output. The model returns line numbers and typed
// values, never a passage: every quote is rebuilt from line_df by ids. In the browser the key lives
// in sessionStorage only and the request goes to the provider only (BYO key).

import { sortedStrings } from "./_py.js";
import { as_tables, attr } from "./contracts.js";
import { line_records } from "./detectors.js";
import { primaries } from "./result.js";
import { ANSWER_CLASSES, Amount, AmountItem, BooleanItem, DateItem, DateValue, Span, TextItem, expected_kind } from "./schemas.js";
import { context_blocks } from "./verbatim.js";

export const PROMPT_VERSION = "guide-rag/gen/1";
export const MAX_CONTEXT_CANDIDATES = 6;

export class NotConfigured extends Error {}

export class LLMConfig {
  constructor({ base_url, api_key, model }) {
    this.base_url = String(base_url || "https://api.openai.com/v1").replace(/\/+$/, "");
    this.api_key = api_key;
    this.model = model || "gpt-4o-mini";
  }

  /** From the "Modèle (optionnel)" panel's sessionStorage entries (never localStorage). */
  static from_session(storage) {
    const key = (storage.getItem("guide_rag_llm_key") || "").trim();
    if (!key) throw new NotConfigured("no model key in this session");
    return new LLMConfig({ base_url: storage.getItem("guide_rag_llm_base_url") || "https://api.openai.com/v1", api_key: key, model: storage.getItem("guide_rag_llm_model") || "gpt-4o-mini" });
  }
}

export const BASE_PROMPT =
  "You answer a newcomer's question about Luxembourg from numbered lines of a public guide. " +
  "The lines are the only source. Return JSON only, matching the schema. " +
  "Cite by doc_id and line numbers (line_start, line_end) that appear in the context; never copy a passage, " +
  "the quotes are rebuilt from the lines by their numbers. " +
  "Set answer_found true only when the lines answer the question; set complete_answer_found true only when " +
  "nothing is missing. List in discovered_keywords the words of the lines a reader would have used for this " +
  "question but which are absent from the question. Do not invent anything outside the lines.";
export const SHAPE_FRAGMENTS = {
  text: "Shape text: one item, text = a short answer in the words of the lines, with one span (doc_id, line_start, line_end).",
  list: "Shape list: one item per element of the list the question asks for, each with its own one-line span.",
  amount: "Shape amount: value as a number, currency (EUR or null), unit (null or e.g. 'mois de loyer'); span = the line that carries the number.",
  date: "Shape date: iso as YYYY-MM-DD and original as written in the line; span = the line that carries the date.",
  boolean: "Shape boolean: boolean true or false as the lines state it; span = the line that states it.",
};
export const CONSTRAINTS_FRAGMENT =
  "Constraints: temperature 0; only line numbers present in the context; an item without a span is invalid; " +
  "when the lines do not answer, return no item and answer_found false.";

/** The JSON schema the model must fill; one item shape per answer kind. */
export function response_schema(kind) {
  const span = {
    type: "object",
    properties: { doc_id: { type: "string" }, line_start: { type: "integer" }, line_end: { type: "integer" } },
    required: ["doc_id", "line_start", "line_end"],
    additionalProperties: false,
  };
  const value_props = {
    text: { text: { type: "string" } },
    list: { text: { type: "string" } },
    amount: { value: { type: "number" }, currency: { type: ["string", "null"] }, unit: { type: ["string", "null"] } },
    date: { iso: { type: "string" }, original: { type: "string" } },
    boolean: { boolean: { type: "boolean" } },
  }[kind];
  const item = { type: "object", properties: { ...value_props, spans: { type: "array", items: span } }, required: Object.keys(value_props).concat(["spans"]), additionalProperties: false };
  return {
    type: "object",
    properties: {
      answer_found: { type: "boolean" },
      complete_answer_found: { type: "boolean" },
      items: { type: "array", items: item },
      discovered_keywords: { type: "array", items: { type: "string" } },
      caveats: { type: "array", items: { type: "string" } },
    },
    required: ["answer_found", "complete_answer_found", "items", "discovered_keywords", "caveats"],
    additionalProperties: false,
  };
}

export function LLMInfo({ model_used, prompt_version, fragments_applied, raw = {} }) {
  return { model_used, prompt_version, fragments_applied, raw };
}

/** A thin OpenAI-compatible chat client over fetch; `transport` lets tests mock the network. */
export class LLMClient {
  constructor(config, { transport = null, timeout = 60000 } = {}) {
    this.config = config;
    this._transport = transport;
    this._timeout = timeout;
  }

  async complete(system, user, schema, schema_name = "guide_rag_answer") {
    const body = {
      model: this.config.model,
      temperature: 0,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      response_format: { type: "json_schema", json_schema: { name: schema_name, schema, strict: true } },
    };
    const url = `${this.config.base_url}/chat/completions`;
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${this.config.api_key}` };
    const send = this._transport || ((u, init) => fetch(u, { ...init, signal: AbortSignal.timeout(this._timeout) }));
    const r = await send(url, { method: "POST", headers, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`model endpoint answered ${r.status}`);
    const data = await r.json();
    const content = data.choices[0].message.content;
    return typeof content === "string" ? JSON.parse(content) : content;
  }
}

/** [system, user, fragments_applied]. The context is numbered lines of the kept candidates. */
export function build_prompt(parsed, retrieval, tables, kind) {
  const fragments = ["base", `shape:${kind}`, "constraints"];
  const system = [BASE_PROMPT, SHAPE_FRAGMENTS[kind], CONSTRAINTS_FRAGMENT].join("\n\n");
  const t = as_tables(tables);
  const shown = retrieval.candidates.filter((c) => c.role === "primary" || c.role === "supporting").slice(0, MAX_CONTEXT_CANDIDATES);
  const lines = line_records(t.line_df, new Set(shown.map((c) => c.context.doc_id)));
  const blocks = [];
  for (const c of shown) {
    const rows = lines.filter((l) => l.doc_id === c.context.doc_id && c.context.line_start <= l.line_num && l.line_num <= c.context.line_end);
    const header = `[${c.candidate_id}] ${c.breadcrumb || c.section_title} (${c.role})`;
    blocks.push(header + "\n" + rows.map((l) => `${l.doc_id} L${l.line_num}: ${l.text}`).join("\n"));
  }
  const user = `Question: ${attr(parsed, "corrected_question") || attr(parsed, "original_question")}\n\nContext:\n` + blocks.join("\n\n");
  return [system, user, fragments];
}

export async function generate_with_llm(parsed, retrieval, tables, client) {
  const kind = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"));
  const [system, user, fragments] = build_prompt(parsed, retrieval, tables, kind);
  const raw = await client.complete(system, user, response_schema(kind));
  const info = LLMInfo({ model_used: client.config.model, prompt_version: PROMPT_VERSION, fragments_applied: fragments, raw });

  const t = as_tables(tables);
  const lines = new Map(line_records(t.line_df).map((l) => [`${l.doc_id}\u0000${l.line_num}`, l.text]));

  const spans_of = (item) => {
    const out = [];
    for (const s of item.spans || []) {
      const doc_id = String(s.doc_id);
      const a = Number(s.line_start);
      const b = Number(s.line_end);
      const texts = [];
      for (let n = a; n <= b; n++) if (lines.has(`${doc_id}\u0000${n}`)) texts.push(lines.get(`${doc_id}\u0000${n}`));
      // The quote is the lines themselves (rule 3); a span outside line_df has no quote and fails validation.
      out.push(Span({ doc_id, line_start: a, line_end: b, quote: texts.length && texts.length === b - a + 1 ? texts.join(" ") : null }));
    }
    return out;
  };

  const items = [];
  for (const it of raw.items || []) {
    const spans = spans_of(it);
    if (kind === "amount") items.push(AmountItem({ amount: Amount({ value: Number(it.value), currency: it.currency ?? null, unit: it.unit ?? null }), spans }));
    else if (kind === "date") items.push(DateItem({ date: DateValue({ iso: String(it.iso), original: String(it.original ?? it.iso) }), spans }));
    else if (kind === "boolean") items.push(BooleanItem({ boolean: Boolean(it.boolean), spans }));
    else {
      // The displayed text is the cited lines, not the model's words: rule 3.
      const text = spans.filter((s) => s.quote).map((s) => s.quote).join(" ") || String(it.text ?? "");
      items.push(TextItem({ text, spans }));
    }
  }
  const extraction = { amount: "computed", date: "computed", boolean: "inferred" }[kind] ?? "verbatim";
  const prim = primaries(retrieval);
  const answer = ANSWER_CLASSES[kind]({
    items,
    extraction_method: items.length ? extraction : "na",
    confidence: retrieval.confidence,
    caveats: (raw.caveats || []).map((c) => String(c)),
    answer_found: Boolean(raw.answer_found) && items.length > 0,
    complete_answer_found: Boolean(raw.complete_answer_found) && items.length > 0,
    context_structured: context_blocks(prim),
    keywords_found: sortedStrings(prim.flatMap((c) => c.matched_keywords)),
    llm_discovered_keywords: sortedStrings((raw.discovered_keywords || []).map((k) => String(k))),
  });
  return [answer, info];
}
