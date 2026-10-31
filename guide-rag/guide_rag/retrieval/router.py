"""The two-level router of SPEC §2b: pages first (corpus_index), then each kept page's own outline.

Deterministic: a keyword tally over the summary line, the page's heading titles, the dictionary
concepts (tags) and the reader's page; one reason string per kept page and per stopped section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .contracts import Term, as_tables, concept_keys, concept_words, content_words, coverage, hints, plan_activation
from .detectors import CURRENT_PAGE_FACTOR, Hit, _s
from .text import concept_label, fold, phrase_in, stems

MAX_PAGES = 3
MIN_SHARE_OF_BEST = 0.34  # a page far behind the best one is noise, not a second chapter
SMALL_SECTION_LINES = 12  # a section this small is read whole; no descent below it
MAX_SECTIONS_PER_LEVEL = 3
DOC_TITLE_BONUS = 2.0  # a document whose title covers the question's words is its chapter
DOC_TITLE_COVERAGE = 0.5


def doc_titles(t: Any) -> dict[str, str]:
    """doc_id -> document title, from corpus_index, page_df or the h1 of toc_df."""
    titles: dict[str, str] = {}
    for df in (t.corpus_index, t.page_df):
        if df is not None and len(df) and "title" in df.columns:
            for r in df[["doc_id", "title"]].to_dict("records"):
                titles.setdefault(str(r["doc_id"]), _s(r.get("title")))
    if t.toc_df is not None and len(t.toc_df):
        for r in t.toc_df.sort_values(["doc_id", "start_line"]).to_dict("records"):
            titles.setdefault(str(r["doc_id"]), _s(r.get("title")))
    return titles


def tag_concepts(tags: list[str], variants_by_concept: Mapping[str, list[str]]) -> set[str]:
    """The concept ids a page's tags name: a tag is a concept id, its label, or one of its variants."""
    lookup: dict[str, str] = {}
    for concept, variants in variants_by_concept.items():
        lookup.setdefault(fold(concept), concept)
        lookup.setdefault(fold(concept_label(concept)), concept)
        for v in variants:
            lookup.setdefault(fold(v), concept)
    found: set[str] = set()
    for tag in tags:
        c = lookup.get(fold(tag))
        if c:
            found.add(c)
        else:
            found.add(tag)  # an unknown tag still matches a question term spelled the same way
    return found


@dataclass
class RoutedPage:
    doc_id: str
    score: float
    reason: str
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class RoutedSection:
    doc_id: str
    section_id: str
    title: str
    breadcrumb: str
    start_line: int
    end_line: int
    level: int
    score: float
    reason: str
    matched_terms: list[str] = field(default_factory=list)
    is_leaf: bool = True


@dataclass
class RouteResult:
    pages: list[RoutedPage]
    sections: list[RoutedSection]
    page_scores: dict[str, float]
    notes: list[str] = field(default_factory=list)


def _tally_text(text: str, terms: list[Term]) -> list[Term]:
    """The terms whose phrase appears in the text (whole words, stems)."""
    ts = stems(text)
    return [t for t in terms if not t.is_regex and stems(t.text) and phrase_in(stems(t.text), ts)]


def _page_titles(toc_df: Any, doc_id: str) -> list[str]:
    if toc_df is None or len(toc_df) == 0:
        return []
    sub = toc_df[toc_df["doc_id"] == doc_id]
    return [_s(t) for t in sub["title"].tolist()]


def _tags(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and value != value):
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]
    return [str(v) for v in value]


def route_level0(parsed: Any, tables: Any, terms: list[Term], max_pages: int = MAX_PAGES,
                 variants_by_concept: Mapping[str, list[str]] | None = None) -> tuple[list[RoutedPage], dict[str, float]]:
    """Level 0: tally the question terms over every page's summary line, headings, tags and title."""
    t = as_tables(tables)
    pages_hint, _, _ = hints(parsed)
    q_concepts = set(concept_keys(terms))
    variants_by_concept = variants_by_concept or {}
    words = content_words(terms, variants_by_concept)
    index = t.corpus_index
    if index is None or len(index) == 0:
        # Without a corpus index the pages come from page_df or line_df; the tally reads headings only.
        src = t.page_df if t.page_df is not None and len(t.page_df) else t.line_df
        doc_ids = sorted(set(src["doc_id"].tolist())) if src is not None and len(src) else []
        rows = [{"doc_id": d, "title": "", "summary_line": "", "tags": []} for d in doc_ids]
    else:
        rows = index.sort_values("doc_id").to_dict("records")

    scored: list[RoutedPage] = []
    for row in rows:
        doc_id = str(row["doc_id"])
        parts: list[str] = []
        matched: list[str] = []
        score = 0.0
        summary_terms = _tally_text(_s(row.get("summary_line")) + " " + _s(row.get("title")), terms)
        if summary_terms:
            score += sum(x.weight for x in summary_terms)
            matched += [x.text for x in summary_terms]
            parts.append(f"{len(summary_terms)} term(s) in the summary line ({', '.join(x.text for x in summary_terms)})")
        title_terms: dict[str, list[str]] = {}
        for title in _page_titles(t.toc_df, doc_id):
            for x in _tally_text(title, terms):
                title_terms.setdefault(x.text, []).append(title)
        if title_terms:
            score += sum(next(x.weight for x in terms if x.text == k) for k in title_terms)
            matched += [k for k in title_terms if k not in matched]
            titles = sorted({v for vs in title_terms.values() for v in vs})
            parts.append(f"heading title match ({', '.join(titles)})")
        tag_hits = sorted(q_concepts & tag_concepts(_tags(row.get("tags")), variants_by_concept))
        if tag_hits:
            score += 1.0 * len(tag_hits)
            parts.append(f"concept(s) in tags ({', '.join(concept_label(c) for c in tag_hits)})")
        # "Trust the TOC": a document titled with the question's words is its chapter.
        doc_cov, _, _ = coverage(concept_words(words), [stems(_s(row.get("title")))]) if words else (0.0, [], [])
        if doc_cov >= DOC_TITLE_COVERAGE:
            score += DOC_TITLE_BONUS * doc_cov
            parts.append(f"document title '{_s(row.get('title'))}' covers {doc_cov:.2f} of the question's words")
        if doc_id in pages_hint:
            if score == 0:
                score = 0.5  # the reader's page is always a candidate chapter
                parts.append("the reader's page, no term found")
            else:
                score *= CURRENT_PAGE_FACTOR
                parts.append(f"the reader's page x{CURRENT_PAGE_FACTOR}")
        if score > 0:
            scored.append(RoutedPage(doc_id, round(score, 3), "; ".join(parts), sorted(set(matched))))

    page_scores = {p.doc_id: p.score for p in scored}
    scored.sort(key=lambda p: (-p.score, p.doc_id))
    kept: list[RoutedPage] = []
    best = scored[0].score if scored else 0.0
    for p in scored:
        if len(kept) >= max_pages:
            break
        if p.score < best * MIN_SHARE_OF_BEST:
            break
        p.reason = f"kept: {p.reason}; tally {p.score}"
        kept.append(p)
    return kept, page_scores


def _page_toc(toc_df: Any, doc_id: str) -> list[dict]:
    if toc_df is None or len(toc_df) == 0:
        return []
    sub = toc_df[toc_df["doc_id"] == doc_id].sort_values("start_line")
    return sub.to_dict("records")


def route_level1(parsed: Any, tables: Any, doc_id: str, terms: list[Term], hits: Iterable[Hit],
                 small: int = SMALL_SECTION_LINES) -> list[RoutedSection]:
    """Level 1: descend the page's outline; stop at a leaf or a section of <= `small` lines."""
    t = as_tables(tables)
    toc = _page_toc(t.toc_df, doc_id)
    if not toc:
        return []
    _, toc_hint, _ = hints(parsed)
    ids = {str(r["section_id"]) for r in toc}
    children: dict[str | None, list[dict]] = {}
    for r in toc:
        parent = _s(r.get("parent_id")) or None
        children.setdefault(parent if parent in ids else None, []).append(r)
    # Hits of this page grouped by line, so a section's tally is the distinct terms in its range.
    line_terms: dict[int, set[str]] = {}
    for h in hits:
        if h.doc_id == doc_id and h.method in ("keyword_lines", "row_match"):
            line_terms.setdefault(h.line_num, set()).add(h.keyword)

    def tally(r: dict) -> tuple[float, list[str], list[str]]:
        title = _s(r.get("title"))
        title_terms = [x.text for x in _tally_text(title, terms)]
        start, end = int(r["start_line"]), int(r["end_line"])
        body_terms: set[str] = set()
        for ln, ts in line_terms.items():
            if start <= ln <= end:
                body_terms |= ts
        score = 2.0 * len(title_terms) + float(len(body_terms))
        if toc_hint and phrase_in(stems(toc_hint), stems(title)):
            score += 2.0
            title_terms.append(f"hint:{toc_hint}")
        return score, title_terms, sorted(body_terms)

    def descend(nodes: list[dict]) -> list[RoutedSection]:
        scored = [(tally(r), r) for r in nodes]
        best = max((s[0] for s, _ in scored), default=0.0)
        if best <= 0:
            return []
        chosen = [(s, r) for s, r in scored if s[0] > 0 and s[0] >= 0.5 * best][:MAX_SECTIONS_PER_LEVEL]
        out: list[RoutedSection] = []
        for (score, title_terms, body_terms), r in chosen:
            sid = str(r["section_id"])
            start, end = int(r["start_line"]), int(r["end_line"])
            size = end - start + 1
            kids = children.get(sid, [])
            why = []
            if title_terms:
                why.append(f"title '{_s(r.get('title'))}' matches {', '.join(title_terms)}")
            if body_terms:
                why.append(f"{len(body_terms)} term(s) in its lines ({', '.join(body_terms)})")
            base = RoutedSection(doc_id, sid, _s(r.get("title")), _s(r.get("breadcrumb")), start, end,
                                 int(r.get("level", 1) or 1), round(score, 3), "", title_terms + body_terms, not kids)
            # A child whose title names a term is a better stop than a small parent read whole.
            kid_title_hit = any(
                _tally_text(_s(k.get("title")), terms) or (toc_hint and phrase_in(stems(toc_hint), stems(_s(k.get("title")))))
                for k in kids
            )
            if not kids:
                base.reason = "; ".join(why) + "; a leaf, stop here"
                out.append(base)
            elif size <= small and not kid_title_hit:
                base.reason = "; ".join(why) + f"; {size} lines, small enough to read whole"
                out.append(base)
            else:
                below = descend(kids)
                if below:
                    out.extend(below)
                else:
                    base.reason = "; ".join(why) + "; no child section carries a term, read whole"
                    out.append(base)
        return out

    result = descend(children.get(None, []))
    result.sort(key=lambda s: (-s.score, s.start_line))
    return result


def route(parsed: Any, plan: Any, tables: Any, terms: list[Term], hits_by_doc: Mapping[str, list[Hit]] | None = None,
          variants_by_concept: Mapping[str, list[str]] | None = None) -> RouteResult:
    """Both levels. `hits_by_doc` (keyword hits per page) sharpens level 1 when given."""
    kept, page_scores = route_level0(parsed, tables, terms, variants_by_concept=variants_by_concept)
    notes: list[str] = []
    sections: list[RoutedSection] = []
    use_toc = plan_activation(plan, "use_toc")[0] if plan is not None else True
    if not kept:
        notes.append("level 0 kept no page: no term of the question in any summary line, heading or tag")
    for p in kept:
        if use_toc is False:
            notes.append(f"{p.doc_id}: use_toc is off, the page is read whole")
            continue
        secs = route_level1(parsed, tables, p.doc_id, terms, (hits_by_doc or {}).get(p.doc_id, []))
        if not secs:
            notes.append(f"{p.doc_id}: no section of the outline carries a term; the page is read whole")
        sections.extend(secs)
    return RouteResult(kept, sections, page_scores, notes)
