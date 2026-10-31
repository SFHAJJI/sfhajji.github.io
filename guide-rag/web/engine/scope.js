// Port of guide_rag/retrieval/scope.py: anchor -> context (SPEC §3). The hit lines are the anchor,
// the context is the paragraph (±3 lines within the section) or the section's own lines, per
// `answer_context`; the context always contains the anchor.

import { _s } from "./_py.js";

export const PARAGRAPH_RADIUS = 3;
export const RUN_GAP = 2; // hit lines at most this far apart form one anchor run

export function SectionBounds(fields) {
  return {
    doc_id: fields.doc_id,
    section_id: fields.section_id,
    title: fields.title,
    breadcrumb: fields.breadcrumb,
    start_line: fields.start_line,
    end_line: fields.end_line,
    anchor_id: fields.anchor_id,
    level: fields.level,
    own_end: fields.own_end, // the last line before the first child heading (end_line for a leaf)
  };
}

export const boundsKey = (doc_id, section_id) => `${doc_id}\u0000${section_id}`;

/** Map "(doc_id, section_id)" -> bounds, read once from toc_df. */
export function section_bounds(toc_df, doc_id = null) {
  const out = new Map();
  if (!toc_df || toc_df.length === 0) return out;
  const records = doc_id === null ? toc_df : toc_df.filter((r) => r.doc_id === doc_id);
  const starts_by_doc = new Map();
  for (const r of records) {
    const d = String(r.doc_id);
    if (!starts_by_doc.has(d)) starts_by_doc.set(d, []);
    starts_by_doc.get(d).push([Number(r.start_line), Number(r.level ?? 1) || 1]);
  }
  for (const r of records) {
    const d = String(r.doc_id);
    const start = Number(r.start_line);
    const end = Number(r.end_line);
    const level = Number(r.level ?? 1) || 1;
    const inner = starts_by_doc.get(d).filter(([s, lv]) => start < s && s <= end && lv > level).map(([s]) => s);
    const b = SectionBounds({
      doc_id: d,
      section_id: String(r.section_id),
      title: _s(r.title),
      breadcrumb: _s(r.breadcrumb) || _s(r.title),
      start_line: start,
      end_line: end,
      anchor_id: _s(r.anchor_id) || null,
      level,
      own_end: inner.length ? Math.min(...inner) - 1 : end,
    });
    out.set(boundsKey(b.doc_id, b.section_id), b);
  }
  return out;
}

/** Group hit lines into runs: lines closer than `gap` belong to one anchor ("anchor small"). */
export function anchor_runs(line_nums, gap = RUN_GAP) {
  const nums = Array.from(new Set(Array.from(line_nums, (n) => Number(n)))).sort((a, b) => a - b);
  const runs = [];
  for (const n of nums) {
    if (runs.length && n - runs[runs.length - 1][1] <= gap) runs[runs.length - 1] = [runs[runs.length - 1][0], n];
    else runs.push([n, n]);
  }
  return runs;
}

/** The context range for an anchor; clipped to the section's own lines (or the page when no section). */
export function context_for(anchor, bounds, answer_context, page_last_line = null) {
  const [a_start, a_end] = anchor;
  const lo = bounds ? bounds.start_line : 1;
  const hi = bounds ? bounds.own_end : page_last_line || a_end;
  let c;
  if (answer_context === "line") c = [a_start, a_end];
  else if (answer_context === "section") c = [lo, hi];
  else c = [Math.max(lo, a_start - PARAGRAPH_RADIUS), Math.min(hi, a_end + PARAGRAPH_RADIUS)]; // paragraph
  // The invariant of rule 5: the context contains the anchor, whatever the clipping did.
  return [Math.min(c[0], a_start), Math.max(c[1], a_end)];
}

export function contains(context, anchor) {
  return context[0] <= anchor[0] && anchor[1] <= context[1];
}

export function lines_in(lines, doc_id, start, end) {
  return lines.filter((l) => l.doc_id === doc_id && start <= l.line_num && l.line_num <= end);
}

/** True when the context is the section's own lines (heading to the line before its first child). */
export function is_whole_section(context, bounds) {
  return Boolean(bounds) && context[0] <= bounds.start_line && context[1] >= bounds.own_end;
}
