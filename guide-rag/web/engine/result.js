// Port of guide_rag/retrieval/result.py: the retrieval result of SPEC §3 and `retrieve()`:
// detectors -> router -> sections -> anchor/context -> arbiter -> confidence, audit and the absence
// sweep. Deterministic and model-free.

import { _s, pyFixed, pyFloatRepr, pyRound, pySum, sortedBy, sortedStrings, maxBy } from "./_py.js";
import { COVERAGE_MIN, CandidateBrief, decide } from "./arbiter.js";
import { as_tables, attr, concept_keys, concept_variants, concept_words, content_words, coverage, hints, plan_activation, question_terms, question_text, title_exact } from "./contracts.js";
import {
  CO_OCCURRENCE_LINE_FACTOR,
  CO_OCCURRENCE_SECTION_FACTOR,
  anchor_regex,
  co_occurrence,
  current_page_boost,
  keyword_lines,
  line_records,
  required_anchor_kind,
  row_match,
  title_match,
} from "./detectors.js";
import { doc_titles, route } from "./router.js";
import { anchor_runs, boundsKey, contains, context_for, section_bounds } from "./scope.js";
import { sweep as run_sweep } from "./sweep.js";
import { is_procedure_question, snippet_of, stems } from "./text.js";

export const ANCHOR_BONUS = 0.5; // a typed anchor on the anchor lines when the answer type asks for one
export const SHARE_WEIGHT = 0.7;
export const MARGIN_WEIGHT = 0.3;
export const ROLE_ORDER = { primary: 0, supporting: 1, tangential: 2, discarded: 3 };
export const BREADCRUMB_SEP = "›";

export function CandidateScope({ doc_id, line_start, line_end, section_id = null }) {
  return { doc_id, line_start, line_end, section_id };
}

export function RetrievedCandidate(f) {
  return {
    candidate_id: f.candidate_id,
    anchor: f.anchor,
    context: f.context,
    snippet: f.snippet,
    text: f.text,
    methods: f.methods,
    matched_keywords: f.matched_keywords,
    matched_concepts: f.matched_concepts ?? [],
    section_title: f.section_title ?? "",
    breadcrumb: f.breadcrumb ?? "",
    url_anchor: f.url_anchor ?? null,
    role: f.role,
    reason: f.reason,
    score: f.score ?? 0.0,
    matched_share: f.matched_share ?? 0.0, // = coverage: the share of the question's words this candidate covers
    coverage: f.coverage ?? 0.0,
    covered_words: f.covered_words ?? [],
    uncovered_words: f.uncovered_words ?? [],
    title_tier: f.title_tier ?? 0,
    title_exact: f.title_exact ?? false, // every content word of the section title is in the question
    page_topic: f.page_topic ?? null, // corpus_index.topic of the page
    topic_match: f.topic_match ?? false, // the page topic is the question's scope topic
    co_occurrence: f.co_occurrence ?? null,
    captures: f.captures ?? [], // typed anchor values found on the anchor lines
  };
}

export function AuditRow({ doc_id, section_id, title, keyword, toc, kept }) {
  return { doc_id, section_id, title, keyword, toc, kept };
}

export function RoutedPageOut({ doc_id, score, reason }) {
  return { doc_id, score, reason };
}

export function RoutedSectionOut({ doc_id, section_id, title, score, reason }) {
  return { doc_id, section_id, title, score, reason };
}

export function SweepConceptOut({ concept, variants, pages_with_hits, line_hits }) {
  return { concept, variants, pages_with_hits, line_hits };
}

export function SweepRowOut({ concept, variant, doc_id, line_num, snippet }) {
  return { concept, variant, doc_id, line_num, snippet };
}

export function RetrievalResult(f) {
  return {
    question_id: f.question_id,
    question: f.question,
    candidates: f.candidates,
    methods_used: f.methods_used,
    methods_skipped: f.methods_skipped,
    not_found: f.not_found,
    not_found_reason: f.not_found_reason ?? null,
    confidence: f.confidence,
    per_section_audit: f.per_section_audit,
    route_pages: f.route_pages ?? [],
    route_sections: f.route_sections ?? [],
    route_notes: f.route_notes ?? [],
    sweep_concepts: f.sweep_concepts ?? [],
    sweep_rows: f.sweep_rows ?? [],
    question_concepts: f.question_concepts ?? [],
    terms: f.terms ?? [],
    content_words: f.content_words ?? [], // {text, weight, weak}
    uncovered_words: f.uncovered_words ?? [], // when not_found for words_not_covered
    answer_context_used: f.answer_context_used ?? "paragraph",
  };
}

export function primaries(retrieval) {
  return retrieval.candidates.filter((c) => c.role === "primary");
}

export function _doc_urls(t) {
  const urls = new Map();
  for (const df of [t.corpus_index, t.page_df]) {
    if (df && df.length && "url" in df[0]) for (const r of df) if (!urls.has(String(r.doc_id))) urls.set(String(r.doc_id), _s(r.url));
  }
  return urls;
}

/** 0.7 x the primary's coverage + 0.3 x its margin over the best non-primary candidate. */
export function confidence_of(primary_share, primary_score, runner_up_score) {
  if (primary_score <= 0) return 0.0;
  const margin = runner_up_score <= 0 ? 1.0 : Math.max(0.0, (primary_score - runner_up_score) / primary_score);
  return pyRound(SHARE_WEIGHT * Math.max(0.0, Math.min(1.0, primary_share)) + MARGIN_WEIGHT * margin, 3);
}

/**
 * The context size: the plan's, except that a procedure question reads the section's steps and a
 * yes/no question reads the paragraph around the sentence that answers.
 */
export function answer_context_for(parsed) {
  const [, , planned] = hints(parsed);
  const answer_type = String(attr(parsed, "answer_type", "text") || "text");
  const shape = String(attr(parsed, "answer_shape", "single") || "single");
  if (answer_type === "boolean" && planned !== "paragraph") {
    return ["paragraph", `answer_context=paragraph: a yes/no question reads the paragraph around the sentence that answers (plan said ${planned})`];
  }
  if (answer_type === "text" && shape === "single" && planned !== "section" && is_procedure_question(question_text(parsed))) {
    return ["section", `answer_context=section: a procedure question ('comment', 'how do I') is answered by a section's steps (plan said ${planned})`];
  }
  return [planned, null];
}

const key2 = (a, b) => `${a}\u0000${b ?? ""}`;

export function retrieve(parsed, plan, tables, dictionary = null) {
  const t = as_tables(tables);
  const by_concept = concept_variants(dictionary, parsed);
  const terms = question_terms(parsed, by_concept);
  const q_concepts = concept_keys(terms);
  const words = content_words(terms, by_concept);
  const [pages_hint] = hints(parsed);
  const [answer_context, context_note] = answer_context_for(parsed);
  const answer_type = String(attr(parsed, "answer_type", "text") || "text");
  const methods_used = [];
  const methods_skipped = {};

  const [use_toc, toc_reason] = plan_activation(plan, "use_toc");
  const [use_rows, rows_reason] = plan_activation(plan, "use_row_level");
  const [use_emb, emb_reason] = plan_activation(plan, "use_embeddings");
  const [use_llm_arb, llm_arb_reason] = plan_activation(plan, "use_llm_arbiter");
  const [do_sweep, sweep_reason] = plan_activation(plan, "sweep_for_absence");
  const [boost_on, boost_reason] = plan_activation(plan, "current_page_boost");
  const boost_pages = boost_on || pages_hint.length ? pages_hint : [];

  // Level 0: which chapters of the one long document.
  let route_result = route(parsed, plan, t, terms, null, by_concept);
  const all_docs = t.line_df && t.line_df.length ? sortedStrings(t.line_df.map((r) => r.doc_id)) : [];
  const scope_docs = route_result.pages.length ? route_result.pages.map((p) => p.doc_id) : all_docs;
  if (!route_result.pages.length) route_result.notes.push("detectors ran over every page because level 0 kept none");
  if (context_note) route_result.notes.push(context_note);
  const lines = line_records(t.line_df, scope_docs);
  const page_last = new Map();
  for (const l of lines) page_last.set(l.doc_id, Math.max(page_last.get(l.doc_id) || 0, l.line_num));

  // The detectors (always the keywords; the others per plan).
  let content_hits = keyword_lines(lines, terms);
  methods_used.push("keyword_lines");
  let title_hits = [];
  if (use_toc) {
    title_hits = title_match(t.toc_df, terms, scope_docs);
    methods_used.push("title_match");
  } else {
    methods_skipped.title_match = toc_reason;
  }
  const kind = required_anchor_kind(answer_type);
  let anchor_hits = [];
  if (kind) {
    anchor_hits = anchor_regex(lines, kind);
    methods_used.push("anchor_regex");
  } else {
    methods_skipped.anchor_regex = `answer type ${answer_type} asks for no typed anchor`;
  }
  if (use_rows) {
    content_hits = content_hits.concat(row_match(t.row_df, terms, lines, scope_docs));
    methods_used.push("row_match");
  } else {
    methods_skipped.row_match = rows_reason;
  }
  methods_skipped.embeddings = !use_emb ? emb_reason : "embeddings are absent from this build";
  methods_skipped.llm_arbiter = !use_llm_arb ? llm_arb_reason : "deterministic arbiter ran first";
  if (boost_pages.length) methods_used.push("current_page_boost");
  else methods_skipped.current_page_boost = boost_reason;

  // Level 1: the outline of each kept page, sharpened by the hits.
  const hits_by_doc = new Map();
  for (const h of content_hits) {
    if (!hits_by_doc.has(h.doc_id)) hits_by_doc.set(h.doc_id, []);
    hits_by_doc.get(h.doc_id).push(h);
  }
  if (route_result.pages.length) {
    const notes = route_result.notes;
    route_result = route(parsed, plan, t, terms, hits_by_doc, by_concept);
    route_result.notes = notes.concat(route_result.notes.filter((n) => !notes.includes(n)));
  }
  const routed = new Set(route_result.sections.map((s) => key2(s.doc_id, s.section_id)));

  // Aggregation to the section.
  const bounds = section_bounds(t.toc_df);
  const titles = doc_titles(t);
  const title_words = concept_words(words);
  // Internal links per line, for the pointer rule ("Voir la fiche : X" defers to X).
  const refs = new Map(); // "doc\0line" -> Set of target doc_ids
  if (t.cross_ref_df && t.cross_ref_df.length && "target_doc_id" in t.cross_ref_df[0]) {
    for (const r of t.cross_ref_df) {
      const target = _s(r.target_doc_id);
      if (target && target !== String(r.doc_id)) {
        const k = key2(String(r.doc_id), Number(r.line_num));
        if (!refs.has(k)) refs.set(k, new Set());
        refs.get(k).add(target);
      }
    }
  }
  const question_topic = attr(attr(parsed, "scope_filters"), "topic") || null;
  const topics = new Map(); // doc_id -> corpus_index.topic
  if (t.corpus_index && t.corpus_index.length && "topic" in t.corpus_index[0]) {
    for (const r of t.corpus_index) topics.set(String(r.doc_id), _s(r.topic) || null);
  }
  const by_section = new Map(); // "doc\0section" -> [Hit]
  for (const h of content_hits) {
    const k = key2(h.doc_id, h.section_id);
    if (!by_section.has(k)) by_section.set(k, { doc_id: h.doc_id, sid: h.section_id, hits: [] });
    by_section.get(k).hits.push(h);
  }
  const titles_by_section = new Map();
  for (const th of title_hits) {
    const k = key2(th.doc_id, th.section_id);
    if (!titles_by_section.has(k)) titles_by_section.set(k, []);
    titles_by_section.get(k).push(th);
  }
  const anchors_by_section = new Map();
  for (const h of anchor_hits) {
    const k = key2(h.doc_id, h.section_id);
    if (by_section.has(k)) {
      // a typed value alone is no candidate
      if (!anchors_by_section.has(k)) anchors_by_section.set(k, []);
      anchors_by_section.get(k).push(h);
    }
  }
  const [co_lines, co_sections] = co_occurrence(content_hits.concat(Array.from(anchors_by_section.values()).flat()));
  const text_of = new Map(lines.map((l) => [key2(l.doc_id, l.line_num), l]));
  const urls = _doc_urls(t);
  const weight_of = new Map(terms.map((x) => [x.text, x.weight]));

  const candidates = [];
  const briefs = [];
  const ordered = sortedBy(Array.from(by_section.values()), (e) => [e.doc_id, e.sid || ""]);
  for (const entry of ordered) {
    const { doc_id, sid } = entry;
    let kw_hits = entry.hits;
    // The heading line repeats the title; when body lines hit, the anchor stays on the body.
    const body_hits = kw_hits.filter((h) => !(text_of.get(key2(h.doc_id, h.line_num)) && text_of.get(key2(h.doc_id, h.line_num)).is_heading));
    kw_hits = body_hits.length ? body_hits : kw_hits;
    const a_hits = anchors_by_section.get(key2(doc_id, sid)) || [];
    const b = sid ? bounds.get(boundsKey(doc_id, sid)) ?? null : null;
    const section_concepts = new Set(kw_hits.map((h) => h.concept_key));
    const t_hits = titles_by_section.get(key2(doc_id, sid)) || [];
    const doc_title = titles.get(doc_id) ?? "";
    const section_title = b ? b.title : "";
    const crumbs = (b ? b.breadcrumb : "").split(BREADCRUMB_SEP).map((c) => c.trim()).filter((c) => c);
    const [title_cov] = coverage(title_words, [stems(section_title)]);
    const [doc_cov] = coverage(title_words, [stems(doc_title)]);
    // The h1 is the page's title: the document tier already speaks for it; exactness is for sub-sections.
    const exact = Boolean(b) && b.level >= 2 && title_exact(section_title, words);
    const scope_docs_set = new Set(scope_docs);
    const points_to = [];
    if (b) {
      for (const [k, targets] of refs) {
        const [d, ln] = k.split("\u0000");
        if (d === doc_id && b.start_line <= Number(ln) && Number(ln) <= b.own_end) for (const target of targets) if (scope_docs_set.has(target)) points_to.push(target);
      }
    }
    const points_to_sorted = sortedStrings(points_to);
    for (const run of anchor_runs(kw_hits.map((h) => h.line_num).concat(a_hits.map((h) => h.line_num)))) {
      const run_kw = kw_hits.filter((h) => run[0] <= h.line_num && h.line_num <= run[1]);
      const run_anchor = a_hits.filter((h) => run[0] <= h.line_num && h.line_num <= run[1]);
      if (!run_kw.length) continue; // a run made of typed values only carries no keyword: not a candidate
      const matched_keywords = sortedStrings(run_kw.map((h) => h.keyword));
      const run_concepts = new Set(run_kw.map((h) => h.concept_key));
      const methods = sortedStrings(run_kw.map((h) => h.method).concat(run_anchor.length ? ["anchor_regex"] : [], t_hits.length ? ["title_match"] : []));
      let co = null;
      let onLine = false;
      for (let ln = run[0]; ln <= run[1]; ln++) if (co_lines.has(key2(doc_id, ln))) onLine = true;
      if (onLine) co = "line";
      else if (co_sections.has(key2(doc_id, sid))) co = "section";
      let score = pySum(matched_keywords.map((k) => weight_of.get(k) ?? 1.0));
      score += pySum(t_hits.map((th) => th.weight));
      score += run_anchor.length ? ANCHOR_BONUS : 0.0;
      score *= co === "line" ? CO_OCCURRENCE_LINE_FACTOR : co === "section" ? CO_OCCURRENCE_SECTION_FACTOR : 1.0;
      score = pyRound(current_page_boost(score, doc_id, boost_pages), 3);
      const run_lines = [];
      for (let n = run[0]; n <= run[1]; n++) if (text_of.has(key2(doc_id, n))) run_lines.push(text_of.get(key2(doc_id, n)));
      // The coverage rule reads the anchor lines, the section title, its ancestors and the document title.
      const cov_texts = run_lines.map((l) => l.stems).concat([stems(section_title)], crumbs.map((c) => stems(c)), [stems(doc_title)]);
      let cov, covered, uncovered, strong;
      if (words.length) {
        [cov, covered, uncovered] = coverage(words, cov_texts);
        strong = words.some((w) => !w.weak && covered.includes(w.text));
      } else {
        // no direct word at all: the share of the question's concepts stands in
        const q_set = new Set(q_concepts);
        const all_concepts = new Set([...run_concepts, ...section_concepts, ...t_hits.map((th) => th.concept_key)].filter((c) => q_set.has(c)));
        cov = q_concepts.length ? pyRound(all_concepts.size / q_concepts.length, 3) : 0.0;
        covered = sortedStrings(all_concepts);
        uncovered = sortedStrings(q_concepts.filter((c) => !all_concepts.has(c)));
        strong = all_concepts.size > 0;
      }
      const ctx = context_for(run, b, answer_context, page_last.get(doc_id) ?? null);
      if (!contains(ctx, run)) throw new Error("rule 5: the context must contain the anchor");
      const ctx_lines = [];
      for (let n = ctx[0]; n <= ctx[1]; n++) if (text_of.has(key2(doc_id, n))) ctx_lines.push(text_of.get(key2(doc_id, n)));
      const anchor_id = run_lines.find((l) => l.anchor_id)?.anchor_id ?? (b ? b.anchor_id : null);
      const url = urls.get(doc_id) ?? "";
      const cid = `${doc_id}#l${run[0]}-l${run[1]}`;
      const brief = new CandidateBrief({
        candidate_id: cid,
        doc_id,
        section_id: sid,
        section_title,
        matched_keywords,
        matched_concepts: sortedStrings([...run_concepts, ...section_concepts]),
        title_keywords: sortedStrings(t_hits.map((th) => th.keyword)),
        co_occurrence: co,
        required_anchor: kind,
        has_required_anchor: run_anchor.length > 0,
        score,
        coverage: cov,
        covered,
        uncovered,
        strong_covered: strong,
        title_coverage: words.length ? title_cov : t_hits.length ? 1.0 : 0.0,
        doc_title_coverage: doc_cov,
        doc_title,
        points_to: points_to_sorted,
        page_score: Number(route_result.page_scores[doc_id] ?? 0.0),
        title_exact: exact,
        section_start: b ? b.start_line : run[0],
        section_end: b ? b.end_line : run[1],
        anchor_start: run[0],
        page_topic: topics.get(doc_id) ?? null,
      });
      briefs.push(brief);
      candidates.push(
        RetrievedCandidate({
          candidate_id: cid,
          anchor: CandidateScope({ doc_id, line_start: run[0], line_end: run[1], section_id: sid }),
          context: CandidateScope({ doc_id, line_start: ctx[0], line_end: ctx[1], section_id: sid }),
          snippet: snippet_of(run_lines.map((l) => l.text).join(" ")),
          text: ctx_lines.map((l) => l.text).join("\n"),
          methods,
          matched_keywords,
          matched_concepts: sortedStrings(run_concepts),
          section_title,
          breadcrumb: b ? b.breadcrumb : "",
          url_anchor: url && anchor_id ? url + "#" + anchor_id : url || null,
          role: "tangential",
          reason: "",
          score,
          matched_share: cov,
          coverage: cov,
          covered_words: covered,
          uncovered_words: uncovered,
          title_tier: brief.title_tier,
          title_exact: exact,
          page_topic: topics.get(doc_id) ?? null,
          co_occurrence: co,
          captures: run_anchor.filter((h) => h.capture).map((h) => ({ ...h.capture, line_num: h.line_num })),
        }),
      );
    }
  }

  // The arbiter: roles with a sentence each.
  const present = sortedStrings(content_hits.map((h) => h.concept_key).concat(title_hits.map((th) => th.concept_key)));
  const strong_present = new Set(words.filter((w) => !w.weak && candidates.some((c) => c.covered_words.includes(w.text))).map((w) => w.text));
  const decisions = decide(briefs, q_concepts, by_concept, answer_type, present, strong_present.size, titles, question_topic);
  const by_id = new Map(briefs.map((b) => [b.candidate_id, b]));
  for (const c of candidates) {
    const d = decisions.get(c.candidate_id);
    c.role = d.role;
    c.reason = d.reason;
    c.title_exact = by_id.get(c.candidate_id).exact_chapter;
    c.topic_match = Boolean(by_id.get(c.candidate_id).topic_match);
  }
  methods_used.push("arbiter_rules");
  const sorted_candidates = sortedBy(candidates, (c) => [ROLE_ORDER[c.role], -(c.title_exact ? 1 : 0), -(c.topic_match ? 1 : 0), -c.coverage, -c.title_tier, -c.score, c.candidate_id]);

  const prim = sorted_candidates.filter((c) => c.role === "primary");
  const others = sorted_candidates.filter((c) => c.role === "supporting" || c.role === "tangential");
  const confidence = prim.length ? confidence_of(prim[0].coverage, prim[0].score, others.length ? Math.max(...others.map((o) => o.score)) : 0.0) : 0.0;

  const not_found = !prim.length;
  let reason = null;
  let uncovered_out = [];
  if (not_found) {
    const term_list = terms.filter((x) => !x.is_regex).map((x) => x.text).join(", ") || "(no keyword)";
    if (!sorted_candidates.length) {
      const where = route_result.pages.length ? `the kept page(s) ${scope_docs.join(", ")}` : "any page";
      reason = `No keyword of the question (${term_list}) hits any line of ${where}.`;
      uncovered_out = words.map((w) => w.text);
    } else {
      const best_cov = maxBy(sorted_candidates, (c) => [c.coverage, c.score]);
      const below = words.length
        ? sorted_candidates.every((c) => c.coverage < COVERAGE_MIN || !words.some((w) => !w.weak && c.covered_words.includes(w.text)))
        : false;
      if (below) {
        uncovered_out = words.filter((w) => !best_cov.covered_words.includes(w.text) || w.weak).map((w) => w.text);
        reason =
          `words_not_covered: ${uncovered_out.join(", ")} — the best candidate ${best_cov.candidate_id} covers only ` +
          `${best_cov.covered_words.join(", ") || "nothing"} (${pyFixed(best_cov.coverage, 2)} of the question's words, below ${pyFloatRepr(COVERAGE_MIN)}).`;
      } else {
        const counts = {};
        for (const r of ["supporting", "tangential", "discarded"]) counts[r] = sorted_candidates.filter((c) => c.role === r).length;
        reason =
          `${sorted_candidates.length} candidate(s) hit (${term_list}) but none qualifies as primary: ` +
          `${counts.supporting} supporting, ${counts.tangential} tangential (one keyword only), ` +
          `${counts.discarded} discarded (a section naming another concept).`;
      }
    }
  }

  // The per-section audit over the kept pages (every page when none was kept).
  const kept_sections = new Set(sorted_candidates.filter((c) => c.role !== "discarded").map((c) => key2(c.anchor.doc_id, c.anchor.section_id)));
  const audit = [];
  const scope_set = new Set(scope_docs);
  for (const b of sortedBy(Array.from(bounds.values()), (b) => [b.doc_id, b.start_line])) {
    if (!scope_set.has(b.doc_id)) continue;
    const k = key2(b.doc_id, b.section_id);
    audit.push(
      AuditRow({
        doc_id: b.doc_id,
        section_id: b.section_id,
        title: b.title,
        keyword: by_section.has(k) ? "Y" : ".",
        toc: titles_by_section.has(k) || routed.has(k) ? "Y" : ".",
        kept: kept_sections.has(k) ? "Y" : ".",
      }),
    );
  }

  let sweep_concepts = [];
  let sweep_rows = [];
  if (do_sweep) {
    const sw = run_sweep(parsed, t, dictionary);
    methods_used.push("sweep");
    sweep_concepts = sw.concepts.map((c) => SweepConceptOut({ concept: c.concept, variants: c.variants, pages_with_hits: c.pages_with_hits, line_hits: c.line_hits }));
    sweep_rows = sw.rows.map((r) => SweepRowOut(r));
  } else {
    methods_skipped.sweep = sweep_reason;
  }

  return RetrievalResult({
    question_id: String(attr(parsed, "question_id", "") || ""),
    question: String(attr(parsed, "original_question", "") || ""),
    candidates: sorted_candidates,
    methods_used,
    methods_skipped,
    not_found,
    not_found_reason: reason,
    confidence,
    per_section_audit: audit,
    route_pages: route_result.pages.map((p) => RoutedPageOut({ doc_id: p.doc_id, score: p.score, reason: p.reason })),
    route_sections: route_result.sections.map((s) => RoutedSectionOut({ doc_id: s.doc_id, section_id: s.section_id, title: s.title, score: s.score, reason: s.reason })),
    route_notes: route_result.notes,
    sweep_concepts,
    sweep_rows,
    question_concepts: q_concepts,
    terms: terms.map((x) => ({ ...x })),
    content_words: words.map((w) => ({ text: w.text, weight: w.weight, weak: w.weak })),
    uncovered_words: uncovered_out,
    answer_context_used: answer_context,
  });
}
