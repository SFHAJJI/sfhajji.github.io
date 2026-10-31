"""The retrieval result of SPEC §3 and `retrieve()`: detectors -> router -> sections -> anchor/context
-> arbiter -> confidence, audit and the absence sweep. Deterministic and model-free.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .arbiter import COVERAGE_MIN, CandidateBrief, decide
from .contracts import (as_tables, attr, concept_keys, concept_variants, concept_words, content_words, coverage,
                        hints, plan_activation, question_terms, question_text, title_exact)
from .detectors import (CO_OCCURRENCE_LINE_FACTOR, CO_OCCURRENCE_SECTION_FACTOR, Hit, TitleHit, _s,
                        anchor_regex, co_occurrence, current_page_boost, keyword_lines, line_records,
                        required_anchor_kind, row_match, title_match)
from .router import RouteResult, doc_titles, route
from .scope import anchor_runs, contains, context_for, section_bounds
from .sweep import sweep as run_sweep
from .text import is_procedure_question, snippet_of, stems

ANCHOR_BONUS = 0.5  # a typed anchor on the anchor lines when the answer type asks for one
SHARE_WEIGHT, MARGIN_WEIGHT = 0.7, 0.3
ROLE_ORDER = {"primary": 0, "supporting": 1, "tangential": 2, "discarded": 3}
BREADCRUMB_SEP = "›"


class CandidateScope(BaseModel):
    doc_id: str
    line_start: int
    line_end: int
    section_id: str | None = None


class RetrievedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    anchor: CandidateScope
    context: CandidateScope
    snippet: str
    text: str
    methods: list[str]
    matched_keywords: list[str]
    matched_concepts: list[str] = Field(default_factory=list)
    section_title: str = ""
    breadcrumb: str = ""
    url_anchor: str | None = None
    role: Literal["primary", "supporting", "tangential", "discarded"]
    reason: str
    score: float = 0.0
    matched_share: float = 0.0  # = coverage: the share of the question's words this candidate covers
    coverage: float = 0.0
    covered_words: list[str] = Field(default_factory=list)
    uncovered_words: list[str] = Field(default_factory=list)
    title_tier: int = 0
    title_exact: bool = False  # an exact-titled chapter: the heading is the reader's words and holds the page's best lines
    page_topic: str | None = None  # corpus_index.topic of the page
    topic_match: bool = False  # the page topic is the question's scope topic
    co_occurrence: str | None = None
    captures: list[dict] = Field(default_factory=list)  # typed anchor values found on the anchor lines


class AuditRow(BaseModel):
    doc_id: str
    section_id: str
    title: str
    keyword: Literal["Y", "."]
    toc: Literal["Y", "."]
    kept: Literal["Y", "."]


class RoutedPageOut(BaseModel):
    doc_id: str
    score: float
    reason: str


class RoutedSectionOut(BaseModel):
    doc_id: str
    section_id: str
    title: str
    score: float
    reason: str


class SweepConceptOut(BaseModel):
    concept: str
    variants: list[str]
    pages_with_hits: list[str]
    line_hits: int


class SweepRowOut(BaseModel):
    concept: str
    variant: str
    doc_id: str
    line_num: int
    snippet: str


class RetrievalResult(BaseModel):
    question_id: str
    question: str
    candidates: list[RetrievedCandidate]
    methods_used: list[str]
    methods_skipped: dict[str, str]
    not_found: bool
    not_found_reason: str | None
    confidence: float
    per_section_audit: list[AuditRow]
    route_pages: list[RoutedPageOut] = Field(default_factory=list)
    route_sections: list[RoutedSectionOut] = Field(default_factory=list)
    route_notes: list[str] = Field(default_factory=list)
    sweep_concepts: list[SweepConceptOut] = Field(default_factory=list)
    sweep_rows: list[SweepRowOut] = Field(default_factory=list)
    question_concepts: list[str] = Field(default_factory=list)
    terms: list[dict] = Field(default_factory=list)
    content_words: list[dict] = Field(default_factory=list)  # {text, weight, weak}
    uncovered_words: list[str] = Field(default_factory=list)  # when not_found for words_not_covered
    answer_context_used: str = "paragraph"

    @property
    def primaries(self) -> list[RetrievedCandidate]:
        return [c for c in self.candidates if c.role == "primary"]


def _doc_urls(t: Any) -> dict[str, str]:
    urls: dict[str, str] = {}
    for df in (t.corpus_index, t.page_df):
        if df is not None and len(df) and "url" in df.columns:
            for r in df[["doc_id", "url"]].to_dict("records"):
                urls.setdefault(str(r["doc_id"]), _s(r.get("url")))
    return urls


def confidence_of(primary_share: float, primary_score: float, runner_up_score: float) -> float:
    """0.7 x the primary's coverage + 0.3 x its margin over the best non-primary candidate."""
    if primary_score <= 0:
        return 0.0
    margin = 1.0 if runner_up_score <= 0 else max(0.0, (primary_score - runner_up_score) / primary_score)
    return round(SHARE_WEIGHT * max(0.0, min(1.0, primary_share)) + MARGIN_WEIGHT * margin, 3)


def answer_context_for(parsed: Any) -> tuple[str, str | None]:
    """The context size: the plan's, except that a procedure question reads the section's steps and
    a yes/no question reads the paragraph around the sentence that answers."""
    _, _, planned = hints(parsed)
    answer_type = str(attr(parsed, "answer_type", "text") or "text")
    shape = str(attr(parsed, "answer_shape", "single") or "single")
    if answer_type == "boolean" and planned != "paragraph":
        return "paragraph", f"answer_context=paragraph: a yes/no question reads the paragraph around the sentence that answers (plan said {planned})"
    if answer_type == "text" and shape == "single" and planned != "section" and is_procedure_question(question_text(parsed)):
        return "section", f"answer_context=section: a procedure question ('comment', 'how do I') is answered by a section's steps (plan said {planned})"
    return planned, None


def retrieve(parsed: Any, plan: Any, tables: Any, dictionary: Any = None) -> RetrievalResult:
    t = as_tables(tables)
    by_concept = concept_variants(dictionary, parsed)
    terms = question_terms(parsed, by_concept)
    q_concepts = concept_keys(terms)
    words = content_words(terms, by_concept)
    pages_hint, _, _ = hints(parsed)
    answer_context, context_note = answer_context_for(parsed)
    answer_type = str(attr(parsed, "answer_type", "text") or "text")
    methods_used: list[str] = []
    methods_skipped: dict[str, str] = {}

    use_toc, toc_reason = plan_activation(plan, "use_toc")
    use_rows, rows_reason = plan_activation(plan, "use_row_level")
    use_emb, emb_reason = plan_activation(plan, "use_embeddings")
    use_llm_arb, llm_arb_reason = plan_activation(plan, "use_llm_arbiter")
    do_sweep, sweep_reason = plan_activation(plan, "sweep_for_absence")
    boost_on, boost_reason = plan_activation(plan, "current_page_boost")
    boost_pages = pages_hint if (boost_on or pages_hint) else []

    # Level 0: which chapters of the one long document.
    route_result: RouteResult = route(parsed, plan, t, terms, variants_by_concept=by_concept)
    all_docs = sorted(set(t.line_df["doc_id"].tolist())) if t.line_df is not None and len(t.line_df) else []
    scope_docs = [p.doc_id for p in route_result.pages] or all_docs
    if not route_result.pages:
        route_result.notes.append("detectors ran over every page because level 0 kept none")
    if context_note:
        route_result.notes.append(context_note)
    lines = line_records(t.line_df, scope_docs)
    page_last = {}
    for l in lines:
        page_last[l.doc_id] = max(page_last.get(l.doc_id, 0), l.line_num)

    # The detectors (always the keywords; the others per plan).
    content_hits: list[Hit] = keyword_lines(lines, terms)
    methods_used.append("keyword_lines")
    title_hits: list[TitleHit] = []
    if use_toc:
        title_hits = title_match(t.toc_df, terms, scope_docs)
        methods_used.append("title_match")
    else:
        methods_skipped["title_match"] = toc_reason
    kind = required_anchor_kind(answer_type)
    anchor_hits: list[Hit] = []
    if kind:
        anchor_hits = anchor_regex(lines, kind)
        methods_used.append("anchor_regex")
    else:
        methods_skipped["anchor_regex"] = f"answer type {answer_type} asks for no typed anchor"
    if use_rows:
        content_hits += row_match(t.row_df, terms, lines, scope_docs)
        methods_used.append("row_match")
    else:
        methods_skipped["row_match"] = rows_reason
    methods_skipped["embeddings"] = emb_reason if not use_emb else "embeddings are absent from this build"
    methods_skipped["llm_arbiter"] = llm_arb_reason if not use_llm_arb else "deterministic arbiter ran first"
    if boost_pages:
        methods_used.append("current_page_boost")
    else:
        methods_skipped["current_page_boost"] = boost_reason

    # Level 1: the outline of each kept page, sharpened by the hits.
    hits_by_doc: dict[str, list[Hit]] = {}
    for h in content_hits:
        hits_by_doc.setdefault(h.doc_id, []).append(h)
    if route_result.pages:
        notes = route_result.notes
        route_result = route(parsed, plan, t, terms, hits_by_doc, variants_by_concept=by_concept)
        route_result.notes = notes + [n for n in route_result.notes if n not in notes]
    routed = {(s.doc_id, s.section_id) for s in route_result.sections}

    # Aggregation to the section.
    bounds = section_bounds(t.toc_df)
    titles = doc_titles(t)
    title_words = concept_words(words)
    question_topic = attr(attr(parsed, "scope_filters"), "topic") or None
    topics: dict[str, str | None] = {}
    if t.corpus_index is not None and len(t.corpus_index) and "topic" in t.corpus_index.columns:
        topics = {str(r["doc_id"]): (_s(r.get("topic")) or None) for r in t.corpus_index[["doc_id", "topic"]].to_dict("records")}
    # Internal links per line, for the pointer rule ("Voir la fiche : X" defers to X).
    refs: dict[tuple[str, int], set[str]] = {}
    if t.cross_ref_df is not None and len(t.cross_ref_df) and "target_doc_id" in t.cross_ref_df.columns:
        for r in t.cross_ref_df[["doc_id", "line_num", "target_doc_id"]].to_dict("records"):
            target = _s(r.get("target_doc_id"))
            if target and target != str(r["doc_id"]):
                refs.setdefault((str(r["doc_id"]), int(r["line_num"])), set()).add(target)
    by_section: dict[tuple[str, str | None], list[Hit]] = {}
    for h in content_hits:
        by_section.setdefault((h.doc_id, h.section_id), []).append(h)
    titles_by_section: dict[tuple[str, str | None], list[TitleHit]] = {}
    for th in title_hits:
        titles_by_section.setdefault((th.doc_id, th.section_id), []).append(th)
    anchors_by_section: dict[tuple[str, str | None], list[Hit]] = {}
    for h in anchor_hits:
        if (h.doc_id, h.section_id) in by_section:  # a typed value alone is no candidate
            anchors_by_section.setdefault((h.doc_id, h.section_id), []).append(h)
    co_lines, co_sections = co_occurrence(content_hits + [h for hs in anchors_by_section.values() for h in hs])
    text_of = {(l.doc_id, l.line_num): l for l in lines}
    urls = _doc_urls(t)
    weight_of = {x.text: x.weight for x in terms}

    candidates: list[RetrievedCandidate] = []
    briefs: list[CandidateBrief] = []
    for key in sorted(by_section, key=lambda k: (k[0], k[1] or "")):
        doc_id, sid = key
        kw_hits = by_section[key]
        # The heading line repeats the title; when body lines hit, the anchor stays on the body.
        body_hits = [h for h in kw_hits if not (text_of.get((h.doc_id, h.line_num)) and text_of[(h.doc_id, h.line_num)].is_heading)]
        kw_hits = body_hits or kw_hits
        a_hits = anchors_by_section.get(key, [])
        b = bounds.get((doc_id, sid)) if sid else None
        section_concepts = {h.concept_key for h in kw_hits}
        t_hits = titles_by_section.get(key, [])
        doc_title = titles.get(doc_id, "")
        section_title = b.title if b else ""
        crumbs = [c.strip() for c in (b.breadcrumb if b else "").split(BREADCRUMB_SEP) if c.strip()]
        title_cov, _, _ = coverage(title_words, [stems(section_title)])
        doc_cov, _, _ = coverage(title_words, [stems(doc_title)])
        # The h1 is the page's title: the document tier already speaks for it; exactness is for sub-sections.
        exact = bool(b) and b.level >= 2 and title_exact(section_title, words)
        points_to = sorted({target for (d, ln), targets in refs.items() if d == doc_id and b and b.start_line <= ln <= b.own_end
                            for target in targets if target in scope_docs})
        for run in anchor_runs([h.line_num for h in kw_hits] + [h.line_num for h in a_hits]):
            run_kw = [h for h in kw_hits if run[0] <= h.line_num <= run[1]]
            run_anchor = [h for h in a_hits if run[0] <= h.line_num <= run[1]]
            if not run_kw:
                continue  # a run made of typed values only carries no keyword: not a candidate
            matched_keywords = sorted({h.keyword for h in run_kw})
            run_concepts = {h.concept_key for h in run_kw}
            methods = sorted({h.method for h in run_kw} | ({"anchor_regex"} if run_anchor else set()) | ({"title_match"} if t_hits else set()))
            co = None
            if any((doc_id, ln) in co_lines for ln in range(run[0], run[1] + 1)):
                co = "line"
            elif (doc_id, sid) in co_sections:
                co = "section"
            score = sum(weight_of.get(k, 1.0) for k in matched_keywords)
            score += sum(th.weight for th in t_hits)
            score += ANCHOR_BONUS if run_anchor else 0.0
            score *= CO_OCCURRENCE_LINE_FACTOR if co == "line" else (CO_OCCURRENCE_SECTION_FACTOR if co == "section" else 1.0)
            score = round(current_page_boost(score, doc_id, boost_pages), 3)
            run_lines = [text_of[(doc_id, n)] for n in range(run[0], run[1] + 1) if (doc_id, n) in text_of]
            # The coverage rule reads the anchor lines, the section title, its ancestors and the document title.
            cov_texts = [l.stems for l in run_lines] + [stems(section_title)] + [stems(c) for c in crumbs] + [stems(doc_title)]
            if words:
                cov, covered, uncovered = coverage(words, cov_texts)
                strong = any(not w.weak for w in words if w.text in covered)
            else:  # no direct word at all: the share of the question's concepts stands in
                all_concepts = (run_concepts | section_concepts | {th.concept_key for th in t_hits}) & set(q_concepts)
                cov = round(len(all_concepts) / len(q_concepts), 3) if q_concepts else 0.0
                covered, uncovered, strong = sorted(all_concepts), sorted(set(q_concepts) - all_concepts), bool(all_concepts)
            ctx = context_for(run, b, answer_context, page_last.get(doc_id))
            assert contains(ctx, run), "rule 5: the context must contain the anchor"
            ctx_lines = [text_of[(doc_id, n)] for n in range(ctx[0], ctx[1] + 1) if (doc_id, n) in text_of]
            anchor_id = next((l.anchor_id for l in run_lines if l.anchor_id), b.anchor_id if b else None)
            url = urls.get(doc_id, "")
            cid = f"{doc_id}#l{run[0]}-l{run[1]}"
            brief = CandidateBrief(
                candidate_id=cid, doc_id=doc_id, section_id=sid, section_title=section_title,
                matched_keywords=matched_keywords, matched_concepts=sorted(run_concepts | section_concepts),
                title_keywords=sorted({th.keyword for th in t_hits}), co_occurrence=co,
                required_anchor=kind, has_required_anchor=bool(run_anchor), score=score,
                coverage=cov, covered=covered, uncovered=uncovered, strong_covered=strong,
                title_coverage=title_cov if words else (1.0 if t_hits else 0.0), doc_title_coverage=doc_cov, doc_title=doc_title,
                points_to=points_to, page_score=float(route_result.page_scores.get(doc_id, 0.0)), title_exact=exact,
                section_start=b.start_line if b else run[0], section_end=b.end_line if b else run[1], anchor_start=run[0],
                page_topic=topics.get(doc_id),
            )
            briefs.append(brief)
            candidates.append(
                RetrievedCandidate(
                    candidate_id=cid,
                    anchor=CandidateScope(doc_id=doc_id, line_start=run[0], line_end=run[1], section_id=sid),
                    context=CandidateScope(doc_id=doc_id, line_start=ctx[0], line_end=ctx[1], section_id=sid),
                    snippet=snippet_of(" ".join(l.text for l in run_lines)),
                    text="\n".join(l.text for l in ctx_lines),
                    methods=methods,
                    matched_keywords=matched_keywords,
                    matched_concepts=sorted(run_concepts),
                    section_title=section_title,
                    breadcrumb=b.breadcrumb if b else "",
                    url_anchor=(url + "#" + anchor_id) if url and anchor_id else (url or None),
                    role="tangential",
                    reason="",
                    score=score,
                    matched_share=cov,
                    coverage=cov,
                    covered_words=covered,
                    uncovered_words=uncovered,
                    title_tier=brief.title_tier,
                    title_exact=exact,
                    page_topic=topics.get(doc_id),
                    co_occurrence=co,
                    captures=[{**h.capture, "line_num": h.line_num} for h in run_anchor if h.capture],
                )
            )

    # The arbiter: roles with a sentence each.
    present = sorted({h.concept_key for h in content_hits} | {th.concept_key for th in title_hits})
    strong_present = {w.text for w in words if not w.weak and any(w.text in c.covered_words for c in candidates)}
    decisions = decide(briefs, q_concepts, by_concept, answer_type, present_concepts=present, n_strong_present=len(strong_present),
                       doc_titles=titles, question_topic=question_topic)
    by_id = {b.candidate_id: b for b in briefs}
    for c in candidates:
        d = decisions[c.candidate_id]
        c.role, c.reason = d.role, d.reason
        c.title_exact = by_id[c.candidate_id].exact_chapter
        c.topic_match = bool(by_id[c.candidate_id].topic_match)
    methods_used.append("arbiter_rules")
    candidates.sort(key=lambda c: (ROLE_ORDER[c.role], -int(c.title_exact), -int(c.topic_match), -c.coverage, -c.title_tier, -c.score, c.candidate_id))

    primaries = [c for c in candidates if c.role == "primary"]
    others = [c for c in candidates if c.role in ("supporting", "tangential")]
    confidence = confidence_of(primaries[0].coverage, primaries[0].score, max((o.score for o in others), default=0.0)) if primaries else 0.0

    not_found = not primaries
    reason = None
    uncovered_out: list[str] = []
    if not_found:
        term_list = ", ".join(x.text for x in terms if not x.is_regex) or "(no keyword)"
        if not candidates:
            where = f"the kept page(s) {', '.join(scope_docs)}" if route_result.pages else "any page"
            reason = f"No keyword of the question ({term_list}) hits any line of {where}."
            uncovered_out = [w.text for w in words]
        else:
            best_cov = max(candidates, key=lambda c: (c.coverage, c.score))
            below = all(c.coverage < COVERAGE_MIN or not any(not w.weak for w in words if w.text in c.covered_words) for c in candidates) if words else False
            if below:
                uncovered_out = [w.text for w in words if w.text not in best_cov.covered_words or w.weak]
                reason = (f"words_not_covered: {', '.join(uncovered_out)} — the best candidate {best_cov.candidate_id} covers only "
                          f"{', '.join(best_cov.covered_words) or 'nothing'} ({best_cov.coverage:.2f} of the question's words, below {COVERAGE_MIN}).")
            else:
                counts = {r: sum(1 for c in candidates if c.role == r) for r in ("supporting", "tangential", "discarded")}
                reason = (f"{len(candidates)} candidate(s) hit ({term_list}) but none qualifies as primary: "
                          f"{counts['supporting']} supporting, {counts['tangential']} tangential (one keyword only), "
                          f"{counts['discarded']} discarded (a section naming another concept).")

    # The per-section audit over the kept pages (every page when none was kept).
    kept_sections = {(c.anchor.doc_id, c.anchor.section_id) for c in candidates if c.role != "discarded"}
    audit: list[AuditRow] = []
    for (doc_id, sid), b in sorted(bounds.items(), key=lambda kv: (kv[0][0], kv[1].start_line)):
        if doc_id not in scope_docs:
            continue
        audit.append(AuditRow(
            doc_id=doc_id, section_id=sid, title=b.title,
            keyword="Y" if (doc_id, sid) in by_section else ".",
            toc="Y" if ((doc_id, sid) in titles_by_section or (doc_id, sid) in routed) else ".",
            kept="Y" if (doc_id, sid) in kept_sections else ".",
        ))

    sweep_concepts: list[SweepConceptOut] = []
    sweep_rows: list[SweepRowOut] = []
    if do_sweep:
        sw = run_sweep(parsed, t, dictionary)
        methods_used.append("sweep")
        sweep_concepts = [SweepConceptOut(concept=c.concept, variants=c.variants, pages_with_hits=c.pages_with_hits, line_hits=c.line_hits) for c in sw.concepts]
        sweep_rows = [SweepRowOut(**r.__dict__) for r in sw.rows]
    else:
        methods_skipped["sweep"] = sweep_reason

    return RetrievalResult(
        question_id=str(attr(parsed, "question_id", "") or ""),
        question=str(attr(parsed, "original_question", "") or ""),
        candidates=candidates,
        methods_used=methods_used,
        methods_skipped=methods_skipped,
        not_found=not_found,
        not_found_reason=reason,
        confidence=confidence,
        per_section_audit=audit,
        route_pages=[RoutedPageOut(doc_id=p.doc_id, score=p.score, reason=p.reason) for p in route_result.pages],
        route_sections=[RoutedSectionOut(doc_id=s.doc_id, section_id=s.section_id, title=s.title, score=s.score, reason=s.reason) for s in route_result.sections],
        route_notes=route_result.notes,
        sweep_concepts=sweep_concepts,
        sweep_rows=sweep_rows,
        question_concepts=q_concepts,
        terms=[x.__dict__ for x in terms],
        content_words=[{"text": w.text, "weight": w.weight, "weak": w.weak} for w in words],
        uncovered_words=uncovered_out,
        answer_context_used=answer_context,
    )
