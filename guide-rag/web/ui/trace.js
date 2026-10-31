// The trace panel (SPEC §5.4): ParsedQuestion, the ExecutionPlan with reasons, the RetrievalResult
// candidates (methods, matched keywords, role, reason), the per-section audit table, the _meta block.

import { el, pre, replace, table } from "./dom.js";

/** Render the trace of a result into `root`; `plan_full` is the dispatcher's plan (with reasons). */
export function render_trace(root, result, plan_full) {
  const trace = result.trace || {};
  const parsed = trace.parsed || {};
  const retrieval = trace.retrieval || { candidates: [], per_section_audit: [] };
  const children = [];

  children.push(el("h3", null, "ParsedQuestion"));
  children.push(
    table(
      [
        { label: "mot-clé", cell: (k) => k.text },
        { label: "poids", cell: (k) => String(k.weight), class: "num" },
        { label: "origine", cell: (k) => k.source + (k.weak ? " · faible" : "") + (k.in_corpus === false ? " · absent du corpus" : "") },
        { label: "concept", cell: (k) => k.concept || "" },
      ],
      parsed.keywords || [],
    ),
  );
  children.push(pre(parsed));

  children.push(el("h3", null, "ExecutionPlan"));
  const activations = plan_full ? plan_activations_of(plan_full) : Object.entries((trace.plan || {}).activations || {});
  children.push(
    table(
      [
        { label: "drapeau", cell: ([name]) => name },
        { label: "actif", cell: ([, a]) => (a.on ? "oui" : "non"), class: "yn" },
        { label: "raison", cell: ([, a]) => a.reason },
      ],
      activations,
    ),
  );
  if (plan_full) {
    children.push(
      el(
        "p",
        { class: "muted" },
        `answer_context = ${plan_full.answer_context} (${plan_full.answer_context_reason}) · chunk_strategy = ${plan_full.chunk_strategy} (${plan_full.chunk_strategy_reason})`,
      ),
    );
  }

  children.push(el("h3", null, "Routage"));
  children.push(
    table(
      [
        { label: "page", cell: (p) => p.doc_id },
        { label: "score", cell: (p) => String(p.score), class: "num" },
        { label: "raison", cell: (p) => p.reason },
      ],
      retrieval.route_pages || [],
    ),
  );
  if ((retrieval.route_sections || []).length) {
    children.push(
      table(
        [
          { label: "section", cell: (s) => `${s.section_id} · ${s.title}` },
          { label: "score", cell: (s) => String(s.score), class: "num" },
          { label: "raison", cell: (s) => s.reason },
        ],
        retrieval.route_sections,
      ),
    );
  }
  if ((retrieval.route_notes || []).length) children.push(el("ul", { class: "caveats" }, retrieval.route_notes.map((n) => el("li", null, n))));

  children.push(el("h3", null, `RetrievalResult · ${retrieval.candidates.length} candidat(s) · confiance ${retrieval.confidence}`));
  children.push(
    el(
      "p",
      { class: "muted" },
      `methods_used : ${(retrieval.methods_used || []).join(", ")} · methods_skipped : ${Object.entries(retrieval.methods_skipped || {})
        .map(([k, v]) => `${k} (${v})`)
        .join("; ")}`,
    ),
  );
  if (retrieval.not_found_reason) children.push(el("p", { class: "muted" }, `not_found : ${retrieval.not_found_reason}`));
  children.push(
    table(
      [
        { label: "candidat", cell: (c) => `${c.candidate_id}\n${c.breadcrumb || c.section_title}` },
        { label: "rôle", cell: (c) => el("span", { class: `role role-${c.role}` }, c.role) },
        { label: "méthodes", cell: (c) => c.methods.join(", ") },
        { label: "mots-clés", cell: (c) => c.matched_keywords.filter((k) => !k.includes("\\")).join(", ") },
        { label: "couverture", cell: (c) => `${c.coverage} · ${c.covered_words.join(", ")}`, class: "num" },
        { label: "score", cell: (c) => String(c.score), class: "num" },
        { label: "raison", cell: (c) => c.reason },
      ],
      retrieval.candidates,
    ),
  );

  children.push(el("h3", null, "Audit par section (mot-clé · titre · retenu)"));
  children.push(
    table(
      [
        { label: "section", cell: (r) => `${r.section_id} · ${r.title}` },
        { label: "mot-clé", cell: (r) => r.keyword, class: "yn" },
        { label: "titre", cell: (r) => r.toc, class: "yn" },
        { label: "retenu", cell: (r) => r.kept, class: "yn" },
      ],
      retrieval.per_section_audit || [],
    ),
  );

  if ((retrieval.sweep_concepts || []).length) {
    children.push(el("h3", null, "Balayage d'absence"));
    children.push(
      table(
        [
          { label: "concept", cell: (c) => c.concept },
          { label: "variantes", cell: (c) => c.variants.join(" · ") },
          { label: "pages", cell: (c) => c.pages_with_hits.join(", ") },
          { label: "lignes", cell: (c) => String(c.line_hits), class: "num" },
        ],
        retrieval.sweep_concepts,
      ),
    );
  }

  children.push(el("h3", null, "_meta"));
  children.push(pre(result.meta));

  replace(root, ...children);
}

function plan_activations_of(plan) {
  const out = [];
  for (const [k, v] of Object.entries(plan)) if (v && typeof v === "object" && "on" in v) out.push([k, v]);
  return out;
}

/** The JSON a reader copies: the GenerationResult plus the dispatcher's full plan. */
export function trace_json(result, plan_full) {
  return JSON.stringify({ answer: result.answer, meta: result.meta, trace: result.trace, plan_full }, null, 2);
}
