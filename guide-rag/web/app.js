// The page: tabs, the data loader (index JSON once, in memory), the ask flow through the JS port of
// the deterministic bricks, and the panels. Everything from the guide is rendered with textContent.

import { ask, load_dictionary, load_tables } from "./engine/cli.js";
import { render_answer } from "./ui/answer.js";
import { el, replace } from "./ui/dom.js";
import { render_evaluation } from "./ui/evaluation.js";
import { IndexTab } from "./ui/index_tab.js";
import { ModelPanel } from "./ui/model.js";
import { SourcePanel } from "./ui/source.js";
import { render_trace, trace_json } from "./ui/trace.js";

const BASE = new URL("./", import.meta.url).href.replace(/web\/$/, ""); // the repository root on GitHub Pages
const INDEX_FILES = ["page_df", "line_df", "toc_df", "row_df", "cross_ref_df", "corpus_index", "coverage"];
const EXAMPLE_QUESTION = "Combien coûte la garantie locative ?";

const $ = (sel) => document.querySelector(sel);
const state = { tables: null, assets: null, coverage: null, loading: null, last: null };

// ----------------------------------------------------------------------------- data

async function fetch_json(path) {
  const r = await fetch(`${BASE}${path}`, { cache: "default" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

/** The index and the dictionary, fetched once and kept in memory (line_df is the big one). */
function ensure_loaded() {
  if (!state.loading) {
    state.loading = (async () => {
      const [index, dictionary] = await Promise.all([
        Promise.all(INDEX_FILES.map((name) => fetch_json(`index/${name}.json`))).then((parts) => Object.fromEntries(parts.map((p, i) => [INDEX_FILES[i], p]))),
        fetch_json("web/data/dictionary.json"),
      ]);
      state.tables = load_tables(index);
      state.coverage = index.coverage;
      state.assets = load_dictionary(dictionary);
      return state;
    })();
  }
  return state.loading;
}

/** The light part first: corpus_index for the page picker, then everything else in the background. */
async function boot_data() {
  try {
    const corpus = await fetch_json("index/corpus_index.json");
    fill_page_select(corpus);
  } catch (e) {
    set_status(`L'index n'a pas pu être chargé (${e.message}).`, true);
  }
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 400));
  idle(() => ensure_loaded().then(show_version).catch((e) => set_status(`L'index n'a pas pu être chargé (${e.message}).`, true)));
}

function fill_page_select(corpus) {
  const select = $("#page-select");
  for (const r of corpus) select.appendChild(el("option", { value: r.doc_id }, r.title));
}

function show_version() {
  const v = state.coverage && state.coverage.index_version ? String(state.coverage.index_version).slice(0, 12) : "";
  $("#foot-version").textContent = v ? `index ${v}… · ${state.coverage.lines_total} lignes, ${state.coverage.pages_total} pages` : "";
}

// ----------------------------------------------------------------------------- tabs

const TABS = ["ask", "methode", "index", "evaluation"];

function current_tab() {
  const hash = location.hash.replace(/^#/, "");
  const name = hash.split("?")[0];
  return TABS.includes(name) ? name : "ask";
}

function show_tab(name) {
  for (const section of document.querySelectorAll(".tab")) section.hidden = section.dataset.tab !== name;
  for (const a of document.querySelectorAll(".topbar a[data-tab]")) a.classList.toggle("is-active", a.dataset.tab === name);
  if (name === "index") ensure_loaded().then(() => index_tab.render(state.tables, state.assets, state.coverage));
  if (name === "evaluation") render_evaluation($("#evaluation-body"), BASE);
  if (name === "methode") run_example();
}

function route() {
  show_tab(current_tab());
  const params = new URLSearchParams((location.hash.split("?")[1] || "").replace(/\+/g, "%20"));
  const q = params.get("q");
  if (q && current_tab() === "ask" && q !== state.last_url_question) {
    state.last_url_question = q;
    $("#question").value = q;
    if (params.get("page")) $("#page-select").value = params.get("page");
    submit_question(q, params.get("page") || null, false);
  }
}

// ----------------------------------------------------------------------------- ask

let source_panel;
let model_panel;
let index_tab;

function set_status(text, is_error = false) {
  const s = $("#status");
  s.textContent = text;
  s.classList.toggle("error", is_error);
}

async function submit_question(question, page, push = true) {
  question = (question || "").trim();
  if (!question) return;
  const button = $("#ask-button");
  button.disabled = true;
  set_status("Chargement de l'index…");
  try {
    await ensure_loaded();
    set_status("Recherche dans le guide…");
    const llm_client = model_panel.client();
    const t0 = performance.now();
    const { result, parsed, plan } = await ask(question, { tables: state.tables, assets: state.assets, page: page || null, llm_client });
    const ms = Math.round(performance.now() - t0);
    state.last = { result, parsed, plan, question, page };
    render_answer($("#answer"), result, {
      parsed,
      tables: state.tables,
      dictionary: state.assets.dictionary,
      on_reask: (text) => {
        $("#question").value = text;
        submit_question(text, $("#page-select").value || null);
      },
      on_show_source: (span) => {
        source_panel.show_result(result, parsed, span);
        $("#source").scrollIntoView({ behavior: "smooth", block: "start" });
      },
    });
    source_panel.show_result(result, parsed);
    render_trace($("#trace-body"), result, plan);
    $("#trace").hidden = false;
    $("#trace").open = false;
    set_status(`${ms} ms dans votre navigateur · ${result.meta.model_used === "no model" ? "sans modèle" : "modèle : " + result.meta.model_used} · ${result.meta.methods_used.length} méthodes`);
    if (push) {
      const params = new URLSearchParams({ q: question });
      if (page) params.set("page", page);
      state.last_url_question = question;
      history.replaceState(null, "", `#ask?${params.toString()}`);
    }
    $("#answer").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    console.error(e);
    set_status(`La question n'a pas pu être traitée : ${e.message}`, true);
  } finally {
    button.disabled = false;
  }
}

async function copy_trace() {
  if (!state.last) return;
  const text = trace_json(state.last.result, state.last.plan);
  const status = $("#copy-status");
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = "copiée";
  } catch (e) {
    const ta = el("textarea", { readonly: true, style: "position:fixed;left:-9999px" }, text);
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      status.textContent = "copiée";
    } catch (e2) {
      status.textContent = "copie impossible : sélectionnez le texte de la trace";
    }
    ta.remove();
  }
  setTimeout(() => (status.textContent = ""), 2500);
}

// ----------------------------------------------------------------------------- the worked example

let example_done = false;
async function run_example() {
  if (example_done) return;
  example_done = true;
  const answer_root = $("#example-answer");
  const trace_root = $("#example-trace");
  replace(answer_root, el("p", { class: "muted" }, "Calcul en cours…"));
  try {
    await ensure_loaded();
    const { result, parsed, plan } = await ask(EXAMPLE_QUESTION, { tables: state.tables, assets: state.assets, page: null, llm_client: null });
    render_answer(answer_root, result, {
      parsed,
      tables: state.tables,
      dictionary: state.assets.dictionary,
      on_reask: (text) => {
        location.hash = `#ask?${new URLSearchParams({ q: text })}`;
      },
      on_show_source: () => {
        location.hash = `#ask?${new URLSearchParams({ q: EXAMPLE_QUESTION })}`;
      },
    });
    render_trace(trace_root, result, plan);
  } catch (e) {
    example_done = false;
    replace(answer_root, el("p", { class: "status error" }, `L'exemple n'a pas pu tourner : ${e.message}`));
  }
}

// ----------------------------------------------------------------------------- boot

function boot() {
  source_panel = new SourcePanel($("#source"));
  model_panel = new ModelPanel($("#model"));
  index_tab = new IndexTab($("#tab-index"));
  ensure_loaded().then(() => source_panel.set_tables(state.tables));

  $("#ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submit_question($("#question").value, $("#page-select").value || null);
  });
  $("#question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit_question($("#question").value, $("#page-select").value || null);
    }
  });
  for (const chip of document.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => {
      $("#question").value = chip.dataset.question;
      submit_question(chip.dataset.question, $("#page-select").value || null);
    });
  }
  $("#copy-trace").addEventListener("click", copy_trace);
  window.addEventListener("hashchange", route);
  boot_data();
  route();
}

boot();
