// The Index tab (SPEC §5.5): page_df, toc_df, line_df browsable per page, the dictionary table,
// the coverage block.

import { el, kv, replace, table } from "./dom.js";

export class IndexTab {
  constructor(root) {
    this.root = root;
    this.select = root.querySelector("#index-page");
    this.coverage = root.querySelector("#coverage");
    this.page_row = root.querySelector("#index-page-row");
    this.toc = root.querySelector("#index-toc");
    this.lines = root.querySelector("#index-lines");
    this.dictionary = root.querySelector("#index-dictionary");
    this.rendered = false;
    this.select.addEventListener("change", () => this.show_page(this.select.value));
  }

  render(tables, assets, coverage) {
    if (this.rendered) return;
    this.rendered = true;
    this.tables = tables;
    replace(
      this.coverage,
      el("h2", null, "Couverture (coverage.json)"),
      kv(
        Object.entries(coverage || {})
          .filter(([k]) => !["data_scripts", "documents", "parsing_methods", "raw_drift"].includes(k))
          .map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)]),
      ),
      coverage && coverage.documents ? el("p", { class: "muted" }, `documents : ${Object.entries(coverage.documents).map(([k, v]) => `${v} ${k}`).join(", ")}`) : null,
      coverage && coverage.data_scripts ? el("ul", { class: "caveats" }, coverage.data_scripts.map((d) => el("li", null, d))) : null,
    );
    replace(this.select, (tables.corpus_index || []).map((r) => el("option", { value: r.doc_id }, `${r.title} (${r.doc_id})`)));
    if (tables.corpus_index && tables.corpus_index.length) this.show_page(tables.corpus_index[0].doc_id);
    this.render_dictionary(assets);
  }

  show_page(doc_id) {
    const t = this.tables;
    const page = (t.page_df || []).find((r) => r.doc_id === doc_id) || {};
    const index = (t.corpus_index || []).find((r) => r.doc_id === doc_id) || {};
    replace(
      this.page_row,
      el("h2", null, "page_df · corpus_index"),
      kv([
        ["doc_id", doc_id],
        ["url", el("a", { href: page.url || index.url, target: "_blank", rel: "noopener" }, page.url || index.url || "")],
        ["titre", page.title],
        ["langue", page.lang],
        ["lignes / sections / tableaux", `${page.n_lines} / ${page.n_sections} / ${page.n_tables}`],
        ["genre", `${page.kind || ""} ${page.category ? "· " + page.category : ""}`],
        ["parsing_method", page.parsing_method],
        ["content_sha256", page.content_sha256 ? page.content_sha256.slice(0, 16) + "…" : null],
        ["relevé le", page.fetched_at],
        ["topic", index.topic],
        ["summary_line", index.summary_line],
        ["tags", (index.tags || []).join(", ")],
      ]),
    );
    const toc = (t.toc_df || []).filter((r) => r.doc_id === doc_id);
    replace(
      this.toc,
      table(
        [
          { label: "section", cell: (r) => r.section_id },
          { label: "niveau", cell: (r) => String(r.level), class: "num" },
          { label: "titre", cell: (r) => `${"  ".repeat(Math.max(0, r.level - 1))}${r.title}` },
          { label: "lignes", cell: (r) => `${r.start_line}–${r.end_line}`, class: "num" },
          { label: "ancre", cell: (r) => r.anchor_id || "" },
        ],
        toc,
      ),
    );
    const lines = (t.line_df || []).filter((r) => r.doc_id === doc_id);
    const rows = (t.row_df || []).filter((r) => r.doc_id === doc_id);
    const refs = (t.cross_ref_df || []).filter((r) => r.doc_id === doc_id);
    replace(
      this.lines,
      el(
        "ol",
        { class: "lines" },
        lines.map((l) =>
          el(
            "li",
            null,
            el("span", { class: "n" }, String(l.line_num)),
            el("span", { class: l.is_heading ? "heading" : null }, `${l.text}`, el("span", { class: "muted" }, `  ⟨${l.element}${l.section_id ? " · " + l.section_id : ""}⟩`)),
          ),
        ),
      ),
      rows.length ? el("h3", null, `row_df · ${rows.length} ligne(s) de tableau`) : null,
      rows.length
        ? table(
            [
              { label: "tableau", cell: (r) => r.table_id },
              { label: "ligne", cell: (r) => String(r.line_num), class: "num" },
              { label: "row_serialized", cell: (r) => r.row_serialized },
            ],
            rows,
          )
        : null,
      refs.length ? el("h3", null, `cross_ref_df · ${refs.length} lien(s) interne(s)`) : null,
      refs.length
        ? table(
            [
              { label: "ligne", cell: (r) => String(r.line_num), class: "num" },
              { label: "vers", cell: (r) => `${r.target_doc_id}${r.target_anchor ? "#" + r.target_anchor : ""}` },
              { label: "contexte", cell: (r) => r.context },
            ],
            refs,
          )
        : null,
    );
  }

  render_dictionary(assets) {
    const d = assets.dictionary;
    const rows = d.concepts_df.map((c) => {
      const by_lang = {};
      for (const v of d.variants_of(c.concept)) (by_lang[v.language] = by_lang[v.language] || []).push(v.keyword + (v.priority === "primary" ? "" : "°"));
      return { ...c, by_lang };
    });
    const size = d.size();
    replace(
      this.dictionary,
      el("p", { class: "muted" }, `${size.concepts} concepts, ${size.variants} variantes (${Object.entries(size).filter(([k]) => k.startsWith("variants_")).map(([k, v]) => `${k.slice(9)} ${v}`).join(", ")}). ° = variante secondaire.`),
      table(
        [
          { label: "concept", cell: (r) => r.concept },
          { label: "topic", cell: (r) => r.topic },
          { label: "fr", cell: (r) => (r.by_lang.fr || []).join(" · ") },
          { label: "en", cell: (r) => (r.by_lang.en || []).join(" · ") },
          { label: "de / lb", cell: (r) => [...(r.by_lang.de || []), ...(r.by_lang.lb || [])].join(" · ") },
          { label: "définition", cell: (r) => r.definition },
        ],
        rows,
      ),
      el("h3", null, "Abréviations"),
      table(
        [
          { label: "abréviation", cell: ([k, a]) => a.abbreviation },
          { label: "développement", cell: ([, a]) => a.expansion },
          { label: "note", cell: ([, a]) => a.note || "" },
        ],
        assets.abbreviations.items(),
      ),
      el("h3", null, "Mots faibles"),
      el("p", { class: "muted" }, `${assets.weak.length} racines (${assets.weak.languages().join(", ")}) : gardées comme mots-clés à 0,3, jamais décisives.`),
    );
  }
}
