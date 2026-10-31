// The demo's page logic: load the guide in the visitor's browser, segment it, index it, answer with a typed card.
// Everything the guide says is rendered with textContent: no HTML of the guide is ever injected here.
import {
  segmentHtml, segmentKnowledge, segmentGuidedFiche, discoverPages, discoverDataScripts,
  buildIndex, expandQuery, search, decide, passage, VERDICTS, THRESHOLDS, pageLabel, onPage, contentWords,
} from "./engine.js";

const GUIDE = "https://lux-guide.github.io/";
const MAX_PAGES = 40;

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
};

const state = { index: null, sections: [], pages: [], readAt: null, lastModified: null, currentPage: null, failures: [] };

// --- loading -----------------------------------------------------------------------------------

function setProgress(text, done = false) {
  const p = $("#progress");
  p.textContent = text;
  p.classList.toggle("muted", done);
}

async function fetchText(url) {
  const res = await fetch(url, { mode: "cors", credentials: "omit", cache: "no-store", redirect: "follow" });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  const lastModified = res.headers.get("last-modified");
  return { text: await res.text(), lastModified };
}

/**
 * Evaluates a data script of the guide inside a sandboxed iframe (an opaque origin: no cookies, no storage,
 * no access to this page) and returns the plain data it exposes as window.KB and window.FICHES.
 */
function evaluateDataScript(code, { timeoutMs = 8000 } = {}) {
  return new Promise((resolve, reject) => {
    const token = `kb-${Math.random().toString(36).slice(2)}`;
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-scripts");
    iframe.setAttribute("hidden", "");
    iframe.setAttribute("aria-hidden", "true");
    iframe.setAttribute("title", "bac à sable");
    const safe = code.replace(/<\/script/gi, "<\\/script");
    const timer = setTimeout(() => { cleanup(); reject(new Error("timeout")); }, timeoutMs);
    function cleanup() { clearTimeout(timer); window.removeEventListener("message", onMessage); iframe.remove(); }
    function onMessage(e) {
      if (e.source !== iframe.contentWindow || !e.data || e.data.token !== token) return;
      cleanup();
      resolve({ kb: e.data.kb ?? null, fiches: e.data.fiches ?? null });
    }
    window.addEventListener("message", onMessage);
    iframe.srcdoc = `<!doctype html><meta charset="utf-8"><script>
      try { ${safe} } catch (e) {}
      function plain(v) { try { return v === undefined ? null : JSON.parse(JSON.stringify(v)); } catch (e) { return null; } }
      parent.postMessage({ token: ${JSON.stringify(token)}, kb: plain(window.KB), fiches: plain(window.FICHES) }, "*");
    <\/script>`;
    document.body.append(iframe);
  });
}

async function loadGuide() {
  const started = performance.now();
  setProgress("Lecture de la page d’accueil du guide…");
  let home;
  try {
    home = await fetchText(GUIDE);
  } catch (err) {
    setProgress(`Le guide n’a pas pu être lu depuis ce navigateur (${err.message}). Rien n’est copié ici : sans lecture, pas de réponse.`, true);
    $("#ask").disabled = true;
    return;
  }
  state.lastModified = home.lastModified;
  const sections = segmentHtml(home.text, GUIDE);
  const pages = [GUIDE];
  const found = discoverPages(home.text, GUIDE, { limit: MAX_PAGES - 1 }).filter((u) => u !== GUIDE);
  const scripts = discoverDataScripts(home.text, GUIDE);
  let n = 0;
  const total = found.length + scripts.length;
  for (const url of found) {
    n++;
    setProgress(`Page ${n} sur ${total} : ${pageLabel(url)}…`);
    try {
      const page = await fetchText(url);
      sections.push(...segmentHtml(page.text, url));
      pages.push(url);
    } catch (err) {
      state.failures.push(`${pageLabel(url)} (${err.message})`);
    }
  }
  for (const url of scripts) {
    n++;
    setProgress(`Fichier de données ${n} sur ${total} : ${pageLabel(url)}…`);
    try {
      const file = await fetchText(url);
      const data = await evaluateDataScript(file.text);
      if (data.kb) sections.push(...segmentKnowledge(data.kb, GUIDE));
      if (data.fiches && typeof data.fiches === "object") {
        for (const f of Object.values(data.fiches)) sections.push(...segmentGuidedFiche(f, GUIDE));
      }
      pages.push(url);
    } catch (err) {
      state.failures.push(`${pageLabel(url)} (${err.message})`);
    }
  }
  state.sections = sections;
  state.pages = pages;
  state.index = buildIndex(sections);
  state.readAt = new Date();
  const distinctPages = new Set(sections.map((s) => s.page)).size;
  const ms = Math.round(performance.now() - started);
  const when = state.readAt.toLocaleString("fr-LU", { dateStyle: "medium", timeStyle: "medium" });
  const modified = state.lastModified ? ` ; le guide lui-même date du ${new Date(state.lastModified).toLocaleDateString("fr-LU", { dateStyle: "long" })} (en-tête Last-Modified)` : "";
  setProgress(`Lu le ${when} en ${ms} ms : ${pages.length} fichier${pages.length > 1 ? "s" : ""} du guide, ${sections.length} sections sur ${distinctPages} pages ou fiches${modified}.${state.failures.length ? ` Non lus : ${state.failures.join(", ")}.` : ""}`, true);
  $("#ask").disabled = false;
  renderCurrentPage();
  const q = new URLSearchParams(location.search).get("q");
  if (q) {
    $("#question").value = q;
    answer(q);
  }
}

// --- the page the reader is on ----------------------------------------------------------------

function renderCurrentPage() {
  const where = $("#where");
  where.replaceChildren();
  const page = new URLSearchParams(location.search).get("page");
  state.currentPage = page && page.trim() ? page.trim() : null;
  if (!state.currentPage) {
    where.append(el("span", { class: "muted small" }, "Aucune page du guide n’est indiquée dans l’adresse (ajoutez ?page=fiche/… ou ?page=prevoyance/ pour simuler le lecteur sur une page : ses sections sont alors favorisées)."));
    return;
  }
  const known = state.sections.some((s) => onPage(s, state.currentPage));
  where.append(
    el("span", { class: "tag" }, "Vous êtes sur :"), " ",
    el("code", {}, state.currentPage),
    known ? el("span", { class: "muted small" }, " (page connue du guide : ses sections sont favorisées, ×1,3)") : el("span", { class: "muted small" }, " (aucune section lue ne porte cette adresse : rien n’est favorisé)"),
  );
}

// --- answering ----------------------------------------------------------------------------------

const LABELS = {
  [VERDICTS.FOUND]: { text: "Trouvé dans le guide", cls: "ok" },
  [VERDICTS.TWO_PAGES]: { text: "Deux pages possibles", cls: "two" },
  [VERDICTS.CLARIFY]: { text: "Précisez", cls: "warn" },
  [VERDICTS.NOT_IN_GUIDE]: { text: "Pas dans ce guide", cls: "no" },
};

function percent(x) { return `${Math.round(x * 100)} %`; }

function renderPassage(section, terms) {
  const p = passage(section.text, terms);
  const node = el("blockquote", { class: "passage", lang: "fr" });
  if (p.truncatedBefore) node.append(el("span", { class: "ellipsis" }, "… "));
  for (const part of p.parts) node.append(part.matched ? el("mark", {}, part.text) : document.createTextNode(part.text));
  if (p.truncatedAfter) node.append(el("span", { class: "ellipsis" }, " …"));
  return node;
}

function crumbs(section) {
  const c = el("div", { class: "crumbs" });
  c.append(el("span", {}, pageLabel(section.page)));
  for (const h of section.headingPath) c.append(el("span", {}, h));
  return c;
}

function openLink(section, label = "Ouvrir la page du guide à cet endroit") {
  let href = section.page;
  if (!section.page.includes("#") && section.anchor) href = `${section.page}#${section.anchor}`;
  return el("a", { href, target: "_blank", rel: "noopener noreferrer external" }, label);
}

function candidateCard(result, terms, title) {
  const card = el("div", { class: "card" });
  if (title) card.append(el("div", { class: "small muted" }, title));
  card.append(el("h3", { style: "margin-top:.25rem" }, result.section.heading));
  card.append(crumbs(result.section));
  card.append(renderPassage(result.section, terms));
  card.append(el("p", { class: "small" }, [
    openLink(result.section), " · ",
    el("span", { class: "muted" }, `pertinence ${percent(result.relevance)} ; mots trouvés : ${result.matched.join(", ")}`),
  ]));
  return card;
}

function answer(query) {
  const out = $("#answer");
  out.replaceChildren();
  if (!state.index) return;
  const expansion = expandQuery(query);
  const results = search(state.index, expansion, { boostPage: state.currentPage, limit: 10 });
  const decision = decide(query, expansion, results, THRESHOLDS);
  const label = LABELS[decision.verdict];
  const terms = [...expansion.terms.keys()];

  const head = el("div", { class: "card", role: "region", "aria-labelledby": "verdict-label" });
  head.append(el("p", { style: "margin:0 0 .5rem" }, [el("span", { class: `pill ${label.cls}`, id: "verdict-label" }, label.text)]));

  if (decision.verdict === VERDICTS.CLARIFY) {
    head.append(el("p", {}, "La question est trop courte ou ne contient aucun mot porteur. Dites de quoi il s’agit : le logement, la voiture, une assurance, la commune, les impôts…"));
    const words = contentWords(query);
    head.append(el("p", { class: "small muted" }, words.length ? `Mots retenus : ${words.join(", ")}.` : "Aucun mot retenu après retrait des mots vides."));
    out.append(head);
    return;
  }
  if (decision.verdict === VERDICTS.NOT_IN_GUIDE) {
    const reasons = {
      no_match: "aucune section du guide ne contient l’un de ces mots",
      below_threshold: `la meilleure section ne réunit que ${percent(results[0]?.relevance ?? 0)} de ce que la question permettait d’atteindre, sous le seuil de ${percent(THRESHOLDS.minRelevance)}`,
      words_not_covered: `la meilleure section ne répond qu’à ${percent(decision.coverage ?? 0)} de vos mots (eux-mêmes ou leurs synonymes), sous le seuil de ${percent(THRESHOLDS.minCoverage)}`,
    };
    head.append(el("p", {}, `Le guide tel qu’il a été lu (${state.sections.length} sections) ne répond pas à cette question : ${reasons[decision.reason] ?? decision.reason}.`));
    head.append(el("p", { class: "small muted" }, `Recherché (vos mots et ceux du dictionnaire) : ${decision.searched.join(", ")}.`));
    head.append(el("p", { class: "small" }, "Une absence est une donnée : elle est dite, et rien n’est inventé à la place."));
    out.append(head);
    if (results.length) {
      const det = el("details", {}, [el("summary", {}, "Les sections les plus proches, pour contrôle")]);
      for (const r of results.slice(0, 3)) det.append(candidateCard(r, terms));
      out.append(det);
    }
    return;
  }
  if (decision.verdict === VERDICTS.TWO_PAGES) {
    head.append(el("p", {}, `Deux pages du guide répondent presque aussi bien (écart de ${percent(decision.margin)}, sous ${percent(THRESHOLDS.closeMargin)}). Laquelle vous intéresse ?`));
    out.append(head);
    out.append(candidateCard(decision.best, terms, "Première page"));
    out.append(candidateCard(decision.second, terms, "Seconde page"));
    const chips = el("div", { class: "chips" });
    for (const r of [decision.best, decision.second]) {
      const b = el("button", { type: "button" }, `Plutôt « ${r.section.heading} »`);
      b.addEventListener("click", () => {
        const u = new URL(location.href);
        u.searchParams.set("page", pageLabel(r.section.page));
        history.replaceState(null, "", u);
        renderCurrentPage();
        answer(query);
      });
      chips.append(b);
    }
    out.append(el("p", { class: "small muted" }, "Choisir une page la marque comme « vous êtes sur » et relance la question avec ce contexte."));
    out.append(chips);
    announce(`${label.text} : ${decision.best.section.heading} ou ${decision.second.section.heading}`);
    return;
  }
  // found
  const best = decision.best;
  head.append(el("p", { class: "small muted", style: "margin:0" }, `Marge sur la page suivante : ${percent(decision.margin)} ; pertinence ${percent(best.relevance)}.`));
  out.append(head);
  out.append(candidateCard(best, terms, onPage(best.section, state.currentPage) ? "Sur la page où vous êtes" : "Sur une autre page du guide"));
  if (results.length > 1) {
    const det = el("details", {}, [el("summary", {}, "Les autres sections comparées")]);
    const ul = el("ul", { class: "plain candidates" });
    for (const r of results.slice(1, 6)) {
      ul.append(el("li", {}, [el("strong", {}, r.section.heading), " ", el("span", { class: "muted small" }, `(${pageLabel(r.section.page)}, pertinence ${percent(r.relevance)})`), " ", openLink(r.section, "ouvrir")]));
    }
    det.append(ul);
    out.append(det);
  }
  announce(`${label.text} : ${best.section.heading}`);
}

function announce(text) {
  const live = $("#live");
  live.textContent = "";
  setTimeout(() => { live.textContent = text; }, 50);
}

// --- wiring -------------------------------------------------------------------------------------

$("#ask").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#question").value;
  const u = new URL(location.href);
  if (q.trim()) u.searchParams.set("q", q); else u.searchParams.delete("q");
  history.replaceState(null, "", u);
  answer(q);
});
for (const b of document.querySelectorAll("#examples button")) {
  b.addEventListener("click", () => {
    $("#question").value = b.dataset.q;
    $("#ask").requestSubmit();
    $("#answer").scrollIntoView({ block: "start" });
  });
}
$("#ask").disabled = true;
loadGuide();
