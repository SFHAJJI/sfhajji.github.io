// The Évaluation tab (SPEC §5.5): the per-type results read from eval/report.json when it exists.

import { el, kv, replace, table } from "./dom.js";

export async function render_evaluation(root, base) {
  let report = null;
  try {
    const r = await fetch(`${base}eval/report.json`, { cache: "no-cache" });
    if (r.ok) report = await r.json();
  } catch (e) {
    report = null;
  }
  if (!report) {
    replace(root, el("p", null, "L'évaluation n'a pas encore été lancée : eval/report.json n'est pas publié. Elle tourne avec ", el("code", null, "guide-rag eval"), " et le fichier est versionné avec l'index."));
    return;
  }
  const per_type = find_per_type(report);
  const head = Object.entries(report).filter(([, v]) => typeof v !== "object" || v === null);
  const children = [];
  if (head.length) children.push(kv(head.map(([k, v]) => [k, String(v)])));
  if (report.totals && typeof report.totals === "object") {
    children.push(el("h3", null, "Totaux"));
    children.push(kv(Object.entries(report.totals).map(([k, v]) => [k, fmt(v)])));
    children.push(el("h3", null, "Par type de question"));
  }
  if (per_type.length) {
    const columns = Array.from(new Set(per_type.flatMap((r) => Object.keys(r))));
    children.push(
      table(
        columns.map((c) => ({ label: c, cell: (r) => fmt(r[c]), class: typeof per_type[0][c] === "number" ? "num" : null })),
        per_type,
      ),
    );
  } else {
    children.push(el("p", { class: "muted" }, "Le rapport ne contient pas de table par type reconnue ; le voici tel quel."));
    children.push(el("pre", null, JSON.stringify(report, null, 2)));
  }
  replace(root, ...children);
}

function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** The per-type rows, whatever key the report uses (per_type, by_type, types, results). */
function find_per_type(report) {
  for (const key of ["per_type", "by_type", "types", "results", "rows"]) {
    const v = report[key];
    if (Array.isArray(v) && v.length && typeof v[0] === "object") return v;
    if (v && typeof v === "object" && !Array.isArray(v)) return Object.entries(v).map(([type, row]) => ({ type, ...(typeof row === "object" ? row : { value: row }) }));
  }
  return [];
}
