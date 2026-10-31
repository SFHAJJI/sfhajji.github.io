// Shared formatting for the page: verdicts, item values, links into the guide, breadcrumbs.

export const VERDICT = {
  complete: { label: "Réponse", cls: "pill-complete" },
  partial: { label: "Réponse partielle", cls: "pill-partial" },
  absence: { label: "Pas dans ce guide", cls: "pill-absence" },
  clarify: { label: "Précisez", cls: "pill-clarify" },
  none: { label: "Non trouvé", cls: "pill-none" },
};

/** The verdict of a GenerationResult, the parsed question deciding "Précisez". */
export function verdict_of(result, parsed) {
  if (parsed && parsed.ambiguity_reason) return "clarify";
  const a = result.answer;
  if (a.kind === "absence") return "absence";
  if (a.answer_found && a.complete_answer_found) return "complete";
  if (a.answer_found) return "partial";
  return "none";
}

export function fmt_number(value) {
  if (typeof value !== "number") return String(value);
  return Number.isInteger(value) ? String(value) : value.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

/** The value of an item as the reader reads it. */
export function item_value(item, kind) {
  if (kind === "amount" && item.amount) {
    const a = item.amount;
    const currency = a.currency === "EUR" ? "€" : a.currency || "";
    return [fmt_number(a.value), currency, a.unit || ""].filter(Boolean).join(" ");
  }
  if (kind === "date" && item.date) return `${item.date.original} (${item.date.iso})`;
  if (kind === "boolean" && typeof item.boolean === "boolean") return item.boolean ? "Oui" : "Non";
  return null; // text and list items are their quote
}

/**
 * The link into the guide for a span: corpus_index.url plus "#anchor_id" when the url has no hash
 * route; when the url is a hash route (/#fiche/bail) the route is kept and the anchor shown as text.
 */
export function guide_link(url, anchor_id) {
  if (!url) return { href: null, anchor_text: anchor_id || null };
  if (url.includes("#")) return { href: url, anchor_text: anchor_id || null };
  return { href: anchor_id ? `${url}#${anchor_id}` : url, anchor_text: null };
}

export function lines_label(start, end) {
  return start === end ? `ligne ${start}` : `lignes ${start}–${end}`;
}

/** The candidate of the retrieval whose anchor holds the span, else the first block of the same page. */
export function locate_span(span, retrieval, context_structured) {
  const cands = (retrieval && retrieval.candidates) || [];
  const exact = cands.find((c) => c.anchor.doc_id === span.doc_id && c.anchor.line_start <= span.line_start && span.line_end <= c.anchor.line_end);
  if (exact) return { breadcrumb: exact.breadcrumb || exact.section_title, section_id: exact.anchor.section_id, candidate: exact };
  const within = cands.find((c) => c.context.doc_id === span.doc_id && c.context.line_start <= span.line_start && span.line_end <= c.context.line_end);
  if (within) return { breadcrumb: within.breadcrumb || within.section_title, section_id: within.anchor.section_id, candidate: within };
  const block = (context_structured || []).find((b) => b.doc_id === span.doc_id);
  if (block) return { breadcrumb: block.breadcrumb || block.section_title, section_id: block.section_id, candidate: null };
  return { breadcrumb: "", section_id: null, candidate: null };
}

export function pct(x) {
  return `${Math.round(x * 100)} %`;
}
