// The answer card (SPEC §5.2): verdict pill, items with verbatim quotes linking into the guide, the
// two booleans and the caveats; the four kinds of evidence on absence; the one clarification with
// its candidate values as buttons on a vague question.

import { el, kv, replace, table } from "./dom.js";
import { VERDICT, guide_link, item_value, lines_label, locate_span, verdict_of } from "./format.js";

/**
 * Render into `root`. `ctx` = {parsed, tables, dictionary, on_reask(question), on_show_source(span)}.
 */
export function render_answer(root, result, ctx) {
  const { parsed, tables, dictionary } = ctx;
  const answer = result.answer;
  const retrieval = result.trace ? result.trace.retrieval : null;
  const verdict = verdict_of(result, parsed);
  const v = VERDICT[verdict];
  const children = [];

  children.push(
    el(
      "div",
      { class: "verdict-row" },
      el("span", { class: `pill ${v.cls}` }, v.label),
      el("span", { class: "meta" }, answer.kind === "absence" ? `raison : ${answer.reason}` : `${answer.kind} · ${answer.extraction_method} · confiance ${answer.confidence.toFixed(2)}`),
      el("span", { class: "meta" }, `modèle : ${result.meta.model_used}`),
    ),
  );

  if (parsed && parsed.ambiguity_reason) children.push(render_clarification(parsed, dictionary, ctx.on_reask));

  if (answer.kind === "absence") {
    children.push(render_absence(answer, retrieval, tables));
  } else {
    const urls = url_map(tables);
    const anchors = anchor_map(tables);
    const kind = answer.kind;
    if (!answer.items.length) {
      children.push(el("p", { class: "muted" }, "Aucun item n'a passé le validateur."));
    }
    answer.items.forEach((item, i) => {
      const value = item_value(item, kind);
      const node = el("div", { class: "item" });
      if (value !== null) node.appendChild(el("p", { class: "item-value" }, value));
      if (kind === "list") node.appendChild(el("p", { class: "item-value" }, `${i + 1}.`));
      for (const span of item.spans) {
        const where = locate_span(span, retrieval, answer.context_structured);
        const anchor_id = anchors.get(`${span.doc_id}\u0000${span.line_start}`) || null;
        const link = guide_link(urls.get(span.doc_id) || "", anchor_id);
        const label = `${where.breadcrumb || span.doc_id} · ${lines_label(span.line_start, span.line_end)}`;
        const caption = el("span", { class: "quote-caption" });
        if (link.href) caption.appendChild(el("a", { href: link.href, target: "_blank", rel: "noopener" }, label));
        else caption.appendChild(el("span", null, label));
        if (link.anchor_text) caption.appendChild(el("span", { class: "anchor-id" }, ` #${link.anchor_text}`));
        caption.appendChild(el("button", { type: "button", class: "linklike", onclick: () => ctx.on_show_source(span) }, " voir la source"));
        node.appendChild(el("figure", { class: "quote-figure" }, el("blockquote", { class: "quote" }, span.quote || item.text || ""), el("figcaption", null, caption)));
      }
      children.push(node);
    });

    children.push(
      el(
        "div",
        { class: "flags" },
        flag("réponse trouvée", answer.answer_found),
        flag("réponse complète", answer.complete_answer_found),
        answer.keywords_found && answer.keywords_found.length ? el("span", { class: "flag muted" }, `mots-clés : ${answer.keywords_found.filter((k) => !k.includes("\\")).join(", ")}`) : null,
      ),
    );
    const caveats = [...answer.caveats];
    for (const c of answer.conflicting_evidence || []) caveats.push(`Valeurs différentes : ${c.values.join(" / ")} (${c.candidate_ids.join(", ")}). ${c.note}`);
    if (caveats.length) children.push(el("ul", { class: "caveats" }, caveats.map((c) => el("li", null, c))));
  }

  replace(root, el("h2", { class: "visually-hidden" }, "Réponse"), ...children);
  root.hidden = false;
}

function flag(label, on) {
  return el("span", { class: "flag" }, el("span", { class: `dot ${on ? "yes" : "no"}` }), `${label} : ${on ? "oui" : "non"}`);
}

export function url_map(tables) {
  const urls = new Map();
  for (const df of [tables.corpus_index, tables.page_df]) for (const r of df || []) if (!urls.has(r.doc_id)) urls.set(r.doc_id, r.url || "");
  return urls;
}

export function anchor_map(tables) {
  const anchors = new Map();
  for (const l of tables.line_df || []) anchors.set(`${l.doc_id}\u0000${l.line_num}`, l.anchor_id || null);
  return anchors;
}

function render_clarification(parsed, dictionary, on_reask) {
  const box = el("div", { class: "clarify" }, el("p", null, parsed.suggested_clarification || "Précisez votre question."));
  if (parsed.candidate_values && parsed.candidate_values.length) {
    const options = el("div", { class: "options" });
    for (const concept of parsed.candidate_values) {
      const label = dictionary ? dictionary.label_of(concept, parsed.language) : concept;
      const topic = dictionary ? dictionary.topic_of(concept) : "";
      const is_default = concept === parsed.proposed_default;
      options.appendChild(
        el(
          "button",
          { type: "button", class: `option${is_default ? " is-default" : ""}`, onclick: () => on_reask(label) },
          label,
          el("small", null, is_default ? `${topic} · proposé par défaut` : topic),
        ),
      );
    }
    box.appendChild(options);
    if (parsed.proposed_default) box.appendChild(el("p", { class: "muted" }, "La réponse ci-dessous suit la valeur proposée par défaut ; touchez une autre valeur pour reposer la question avec elle."));
  }
  return box;
}

function render_absence(answer, retrieval, tables) {
  const cov = answer.parse_coverage || {};
  const box = el("div", { class: "evidence" });
  box.appendChild(el("h3", null, "1. Ce que l'index couvre"));
  box.appendChild(
    kv([
      ["pages", `${cov.pages_with_text ?? "?"} avec du texte sur ${cov.pages_total ?? "?"}`],
      ["lignes", cov.lines_total],
      ["sections", cov.sections_total],
      ["tableaux", cov.tables_total],
      ["liens internes", cov.cross_refs],
      ["relevé le", cov.fetched_at],
      ["version de l'index", cov.index_version ? String(cov.index_version).slice(0, 12) + "…" : null],
    ]),
  );
  box.appendChild(el("h3", null, "2. Les concepts cherchés, avec leurs variantes et leurs comptes"));
  box.appendChild(
    table(
      [
        { label: "concept", cell: (r) => r.concept.replace(/_/g, " ") },
        { label: "variantes cherchées", cell: (r) => r.variants.join(" · ") },
        { label: "pages", cell: (r) => String(r.pages_with_hits.length), class: "num" },
        { label: "lignes", cell: (r) => String(r.line_hits), class: "num" },
      ],
      answer.searched_concepts,
    ),
  );
  if (retrieval) {
    const rows = retrieval.sweep_rows || [];
    const pages = new Set(rows.map((r) => r.doc_id));
    const scanned = tables && tables.line_df ? tables.line_df.length : null;
    const n_pages = tables && tables.line_df ? new Set(tables.line_df.map((l) => l.doc_id)).size : null;
    box.appendChild(el("h3", null, "3. Le balayage exhaustif"));
    box.appendChild(
      el(
        "p",
        null,
        `Chaque variante de chaque concept, en expression regulière à mots entiers, sur ${scanned ?? "toutes les"} lignes de ${n_pages ?? "toutes les"} pages (pas un top-k) : ${rows.length} ligne(s) touchée(s) sur ${pages.size} page(s)${pages.size ? " : " + Array.from(pages).sort().join(", ") : ""}.`,
      ),
    );
  }
  box.appendChild(el("h3", null, "4. Les mentions les plus proches, et pourquoi elles ne répondent pas"));
  if (!answer.closest_mentions.length) box.appendChild(el("p", { class: "muted" }, "Aucune mention : aucun des mots de la question n'apparaît dans le guide."));
  for (const m of answer.closest_mentions) {
    box.appendChild(
      el(
        "div",
        { class: "mention" },
        el("div", { class: "muted" }, `${m.doc_id} · ligne ${m.line_num}`),
        el("div", { class: "snippet" }, m.snippet),
        el("div", { class: "why" }, m.why_not_an_answer),
      ),
    );
  }
  if (answer.suggestion) box.appendChild(el("p", null, el("strong", null, "Suggestion : "), answer.suggestion));
  return box;
}
