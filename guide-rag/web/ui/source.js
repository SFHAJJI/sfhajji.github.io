// The source panel (SPEC §5.3): the page's line_df as numbered lines, the anchor lines highlighted,
// the context shaded, a scope picker (ligne / paragraphe / section / page) that re-shades.

import { boundsKey, context_for, section_bounds } from "../engine/scope.js";
import { el, clear, replace } from "./dom.js";
import { guide_link } from "./format.js";
import { url_map } from "./answer.js";

const SCOPE_OF_CONTEXT = { line: "line", paragraph: "paragraph", section: "section" };

export class SourcePanel {
  constructor(root) {
    this.root = root;
    this.select = root.querySelector("#source-page");
    this.open = root.querySelector("#source-open");
    this.list = root.querySelector("#source-lines");
    this.scope = root.querySelector("#scope-picker");
    this.tables = null;
    this.bounds = null;
    this.state = null; // {doc_id, anchors: [[a,b]], section_id, answer_context}
    this.select.addEventListener("change", () => this.show_doc(this.select.value));
    this.scope.addEventListener("change", () => this.paint());
  }

  set_tables(tables) {
    this.tables = tables;
    this.bounds = section_bounds(tables.toc_df);
    this.urls = url_map(tables);
  }

  /** Show a result: the pages of its primary candidates (or of its mentions) in the select, the first chosen. */
  show_result(result, parsed, focus_span = null) {
    const retrieval = result.trace ? result.trace.retrieval : null;
    const answer = result.answer;
    const answer_context = retrieval ? retrieval.answer_context_used : "paragraph";
    const docs = [];
    const candidates = retrieval ? retrieval.candidates.filter((c) => c.role === "primary") : [];
    for (const c of candidates) if (!docs.includes(c.anchor.doc_id)) docs.push(c.anchor.doc_id);
    if (answer.kind === "absence") for (const m of answer.closest_mentions) if (!docs.includes(m.doc_id)) docs.push(m.doc_id);
    if (!docs.length && retrieval) for (const c of retrieval.candidates) if (!docs.includes(c.anchor.doc_id)) docs.push(c.anchor.doc_id);
    if (!docs.length) {
      this.root.hidden = true;
      return;
    }
    this.result = result;
    this.answer_context = answer_context;
    clear(this.select);
    for (const d of docs) this.select.appendChild(el("option", { value: d }, this.title_of(d)));
    const first = focus_span ? focus_span.doc_id : docs[0];
    this.select.value = first;
    const scope = this.scope.querySelector(`input[value="${SCOPE_OF_CONTEXT[answer_context] || "paragraph"}"]`);
    if (scope) scope.checked = true;
    this.root.hidden = false;
    this.show_doc(first, focus_span);
  }

  title_of(doc_id) {
    const row = (this.tables.corpus_index || []).find((r) => r.doc_id === doc_id);
    return row ? row.title : doc_id;
  }

  show_doc(doc_id, focus_span = null) {
    const retrieval = this.result.trace ? this.result.trace.retrieval : null;
    const answer = this.result.answer;
    // The anchors on this page: the primary candidates' anchors (or the mentions on absence), or the span asked for.
    let anchors = [];
    let section_id = null;
    if (focus_span && focus_span.doc_id === doc_id) {
      anchors = [[focus_span.line_start, focus_span.line_end]];
    } else if (retrieval) {
      for (const c of retrieval.candidates) {
        if (c.role === "primary" && c.anchor.doc_id === doc_id) anchors.push([c.anchor.line_start, c.anchor.line_end]);
      }
      if (!anchors.length && answer.kind === "absence") for (const m of answer.closest_mentions) if (m.doc_id === doc_id) anchors.push([m.line_num, m.line_num]);
      if (!anchors.length) for (const c of retrieval.candidates) if (c.anchor.doc_id === doc_id) anchors.push([c.anchor.line_start, c.anchor.line_end]);
    }
    if (retrieval) {
      const c = retrieval.candidates.find((c) => c.anchor.doc_id === doc_id && anchors.some(([a, b]) => c.anchor.line_start <= a && b <= c.anchor.line_end));
      if (c) section_id = c.anchor.section_id;
    }
    this.state = { doc_id, anchors, section_id };
    const url = this.urls.get(doc_id) || "";
    const first_line = (this.tables.line_df || []).find((l) => l.doc_id === doc_id && anchors.some(([a]) => a === l.line_num));
    const link = guide_link(url, first_line ? first_line.anchor_id : null);
    if (link.href) {
      this.open.href = link.href;
      this.open.hidden = false;
    } else this.open.hidden = true;
    this.render_lines();
    this.paint();
    const target = this.list.querySelector(".in-anchor");
    if (target) target.scrollIntoView({ block: "center", behavior: "auto" });
  }

  render_lines() {
    const { doc_id } = this.state;
    const lines = (this.tables.line_df || []).filter((l) => l.doc_id === doc_id);
    replace(
      this.list,
      lines.map((l) =>
        el(
          "li",
          { dataset: { n: String(l.line_num), section: l.section_id || "" }, id: `src-${doc_id}-${l.line_num}` },
          el("span", { class: "n" }, String(l.line_num)),
          el("span", { class: l.is_heading ? "heading" : null }, l.text),
        ),
      ),
    );
  }

  /** Re-shade for the chosen scope: the anchor lines always, the context per scope. */
  paint() {
    if (!this.state) return;
    const scope = (this.scope.querySelector("input:checked") || {}).value || "paragraph";
    const { doc_id, anchors } = this.state;
    const page_last = Math.max(0, ...Array.from(this.list.children, (li) => Number(li.dataset.n)));
    const contexts = [];
    for (const run of anchors) {
      if (scope === "page") {
        contexts.push([1, page_last]);
        continue;
      }
      const line = (this.tables.line_df || []).find((l) => l.doc_id === doc_id && l.line_num === run[0]);
      const sid = line ? line.section_id : this.state.section_id;
      const b = sid ? this.bounds.get(boundsKey(doc_id, sid)) || null : null;
      contexts.push(context_for(run, b, scope, page_last));
    }
    for (const li of this.list.children) {
      const n = Number(li.dataset.n);
      const in_anchor = anchors.some(([a, b]) => a <= n && n <= b);
      const in_context = contexts.some(([a, b]) => a <= n && n <= b);
      li.classList.toggle("in-anchor", in_anchor);
      li.classList.toggle("in-context", in_context && !in_anchor);
    }
  }
}
