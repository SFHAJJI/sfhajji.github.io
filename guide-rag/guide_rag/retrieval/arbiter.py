"""The deterministic arbiter of SPEC §3: a role and one reason sentence per candidate.

Rules, in order (a JS port must mirror them):
1. a section whose title names another dictionary concept (none of the question's), with no
   co-occurrence and no title match -> discarded ("names X, not Y"); when the question has a scope
   topic, such a section on a page of another topic is discarded even with a co-occurrence as soon
   as an eligible candidate sits on a page of the question's topic;
2. the answer type asks for a typed anchor (amount, date, phone, ...): among candidates that cover
   the question equally and sit in equally titled sections, the ones carrying it rank first
   ("two-signal match"); when the best section carries none, it stays primary and the typed value
   is reported missing;
3. the coverage rule: the question's content words (weighted, generic words at 0.3) must be covered
   by the candidate's anchor lines, its section title, its breadcrumb or its document title above
   COVERAGE_MIN, with at least one non-generic word covered; otherwise at most supporting;
4. ranking: candidates rank by (exact-titled chapter, page topic = the question's scope topic,
   coverage, document-title tier, section-title tier, typed anchor, section-title coverage, page
   tally, score) — "trust the TOC": a sub-section
   whose heading is made of the reader's own words and which holds the page's best-covering lines
   comes first; a title tier is 1 when the title covers >= TITLE_COVERAGE of the question's
   concept words; a section
   whose own lines link to another document that covers the question as well defers to it (the
   pointer rule); among equals the router's level-0 page tally decides; the best is primary, as are
   the ones of the same coverage and tiers within PRIMARY_SHARE of its score;
5. a primary also needs a title (tier >= 1), a content co-occurrence, or a question with a single
   strong word present; a single keyword hit without a title is tangential;
6. the rest: supporting when a title or a co-occurrence backs it, tangential otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .text import concept_label, phrase_in, stems

PRIMARY_SHARE = 0.8  # a candidate of the same tier and coverage this close to the best one is a primary too
PAGE_SHARE = 0.5  # ... provided the router ranks its page at least this close to the best page
COVERAGE_MIN = 0.34  # the share of the question's words a primary must cover
TITLE_COVERAGE = 0.5  # a title that covers this much of the question's words is "an exact title match"
Role = str  # primary | supporting | tangential | discarded


@dataclass
class CandidateBrief:
    """What the arbiter reads about a candidate; the LLM arbiter would read the same table."""

    candidate_id: str
    doc_id: str
    section_id: str | None
    section_title: str
    matched_keywords: list[str]
    matched_concepts: list[str]
    title_keywords: list[str] = field(default_factory=list)
    co_occurrence: str | None = None  # "line" | "section" | None
    required_anchor: str | None = None  # the anchor kind the answer type asks for
    has_required_anchor: bool = False
    score: float = 0.0
    coverage: float = 1.0
    covered: list[str] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    strong_covered: bool = True
    title_coverage: float = 0.0  # of the question's concept words, by the section title
    doc_title_coverage: float = 0.0  # of the question's concept words, by the document title
    doc_title: str = ""
    points_to: list[str] = field(default_factory=list)  # documents the section's own lines link to ("Voir la fiche")
    page_score: float = 0.0  # the level-0 tally of the candidate's page: the router's chapter wins among equals
    title_exact: bool = False  # every content word of the section title is a word the reader typed
    section_start: int = 0
    section_end: int = 0
    anchor_start: int = 0
    exact_chapter: bool = False  # set by decide(): exact title and the section holds the page's best-covering candidate
    page_topic: str | None = None  # corpus_index.topic of the candidate's page
    topic_match: int = 0  # set by decide(): 1 when the page topic is the question's scope topic

    @property
    def doc_tier(self) -> int:
        return 1 if self.doc_title_coverage >= TITLE_COVERAGE else 0

    @property
    def section_tier(self) -> int:
        return 1 if self.title_coverage >= TITLE_COVERAGE else 0

    @property
    def title_tier(self) -> int:
        """3: document and section titles name the question; 2: the document title; 1: the section title; 0: none."""
        return 2 * self.doc_tier + self.section_tier

    @property
    def anchor_ok(self) -> int:
        """1 when the answer type asks for no typed anchor or the lines carry it ("two-signal match")."""
        return 1 if (not self.required_anchor or self.has_required_anchor) else 0

    @property
    def rank_key(self) -> tuple[int, int, float, int, int, int, float, float, float]:
        """An exact-titled chapter first ("trust the TOC"); then a page whose topic is the question's
        scope topic; then how much of the question the candidate covers; among equals the document
        title, then the section title; then the typed anchor the answer type asks for; then the
        section title's own coverage (the h1 section beats a sub-section of the same page); then
        the router's level-0 page tally; then the score."""
        return (int(self.exact_chapter), self.topic_match, round(self.coverage, 2), self.doc_tier, self.section_tier, self.anchor_ok,
                round(self.title_coverage, 2), round(self.page_score, 2), self.score)

    def same_rank_class(self, other: "CandidateBrief") -> bool:
        return (self.exact_chapter == other.exact_chapter and self.topic_match == other.topic_match
                and round(self.coverage, 2) >= round(other.coverage, 2) - 0.01
                and self.anchor_ok == other.anchor_ok and self.doc_tier == other.doc_tier and self.section_tier == other.section_tier)

    def contains_anchor_of(self, other: "CandidateBrief") -> bool:
        return other.doc_id == self.doc_id and self.section_start <= other.anchor_start <= self.section_end


@dataclass(frozen=True)
class Decision:
    role: Role
    reason: str


def title_concepts(title: str, variants_by_concept: Mapping[str, list[str]]) -> list[str]:
    """The dictionary concepts a section title names (whole-phrase match on any variant)."""
    ts = stems(title)
    found: list[str] = []
    for concept, variants in variants_by_concept.items():
        for v in variants:
            vs = stems(v)
            if vs and phrase_in(vs, ts):
                found.append(concept)
                break
    return found


def _join(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    if not items:
        return ""
    if len(items) == 1:
        return f"'{items[0]}'"
    return ", ".join(f"'{x}'" for x in items[:-1]) + f" and '{items[-1]}'"


def decide(briefs: list[CandidateBrief], question_concepts: list[str],
           variants_by_concept: Mapping[str, list[str]], answer_type: str = "text",
           present_concepts: list[str] | None = None, n_strong_present: int | None = None,
           doc_titles: Mapping[str, str] | None = None, question_topic: str | None = None) -> dict[str, Decision]:
    """Roles for every candidate; deterministic, reasons as sentences.

    `present_concepts` are the question concepts that hit at least one line of the kept pages;
    `n_strong_present` the number of non-generic content words present on those pages (a single
    present word cannot co-occur with another, so the one-term rule applies); `question_topic` is
    the question's scope topic (parsed.scope_filters.topic), compared with each page's topic.
    """
    doc_titles = doc_titles or {}
    # "other" is the topic of no subject: it never matches, on either side.
    if question_topic == "other":
        question_topic = None
    for b in briefs:
        b.topic_match = 1 if (question_topic and b.page_topic == question_topic) else 0
    q_set = set(question_concepts)
    present = [c for c in question_concepts if c in set(present_concepts)] if present_concepts is not None else list(question_concepts)
    one_term = (n_strong_present if n_strong_present is not None else len(present)) < 2
    # "names X, not Y" needs a Y: the rule fires only when the question names a dictionary concept.
    y_keys = [c for c in question_concepts if c in variants_by_concept]
    decisions: dict[str, Decision] = {}
    eligible: list[CandidateBrief] = []

    # Pass 1: the exclusions, so "best" is computed over the candidates that can still answer.
    y = " / ".join(concept_label(c) for c in y_keys)
    foreign: dict[str, str] = {}  # candidates whose section title names a concept absent from the question
    for b in briefs:
        named = [c for c in title_concepts(b.section_title, variants_by_concept) if c not in q_set]
        backed = bool(b.co_occurrence) or bool(b.title_keywords) or b.title_tier >= 1
        kws = _join(b.matched_keywords)
        if named and y_keys:
            foreign[b.candidate_id] = concept_label(named[0])
        if named and not backed and y_keys:
            decisions[b.candidate_id] = Decision("discarded", f"The section '{b.section_title}' names '{foreign[b.candidate_id]}', not '{y}'; its lines carry only {kws}.")
            continue
        if b.coverage < COVERAGE_MIN or not b.strong_covered:
            role = "supporting" if backed else "tangential"
            why = "only generic words" if (b.covered and not b.strong_covered) else f"only {_join(b.covered) or 'nothing'}"
            decisions[b.candidate_id] = Decision(
                role, f"Covers {why} ({b.coverage:.2f} of the question's words); {_join(b.uncovered)} not covered: {role}."
            )
            continue
        eligible.append(b)

    # A foreign-titled section on a page of another topic is discarded even when its lines co-occur,
    # as soon as an eligible candidate sits on a page whose topic is the question's ("names X, not Y").
    on_topic = [o for o in eligible if o.topic_match and o.candidate_id not in foreign]
    if question_topic and on_topic:
        kept: list[CandidateBrief] = []
        for b in eligible:
            if b.candidate_id in foreign and not b.topic_match:
                o = on_topic[0]
                decisions[b.candidate_id] = Decision(
                    "discarded", f"The section '{b.section_title}' names '{foreign[b.candidate_id]}', not '{y}': its page's topic "
                                 f"'{b.page_topic or 'none'}' is not the question's '{question_topic}', and {o.candidate_id} answers on a '{question_topic}' page."
                )
            else:
                kept.append(b)
        eligible = kept

    if not eligible:
        return decisions
    ranked = sorted(eligible, key=lambda x: (tuple(-v for v in x.rank_key), x.candidate_id))

    # The pointer rule: a section whose own lines link to another document ("Voir la fiche : X")
    # defers to X when X holds a candidate that covers the question as well; the pointer stays
    # as "also answered here". A document never defers to one that points back at it.
    deferred: dict[str, str] = {}
    for b in ranked:
        for target in b.points_to:
            holder = next((o for o in ranked if o.doc_id == target and o.candidate_id not in deferred
                           and o.coverage >= b.coverage - 0.01 and b.doc_id not in o.points_to), None)
            if holder is not None:
                deferred[b.candidate_id] = target
                break
    for b in ranked:
        if b.candidate_id in deferred:
            target = deferred[b.candidate_id]
            decisions[b.candidate_id] = Decision(
                "supporting", f"Covers {_join(b.covered)} (coverage {b.coverage:.2f}) and points to '{doc_titles.get(target, target)}' "
                              f"(Voir la fiche), which covers the question as well: supporting (also answered here)."
            )
    eligible = [b for b in ranked if b.candidate_id not in deferred]
    if not eligible:
        return decisions
    # The exact-titled chapter: a sub-section whose heading is made of the reader's words and which
    # holds the best-covering candidate of the page (itself or a step below it) is the answer whole.
    best_cov = max(round(b.coverage, 2) for b in eligible)
    for b in eligible:
        b.exact_chapter = b.title_exact and any(round(o.coverage, 2) >= best_cov - 0.01 and b.contains_anchor_of(o) for o in eligible)
    eligible.sort(key=lambda x: (tuple(-v for v in x.rank_key), x.candidate_id))
    best = eligible[0]

    # Pass 2: the roles.
    for b in eligible:
        kws = _join(b.matched_keywords)
        cov = f"coverage {b.coverage:.2f}"
        # A second primary: same coverage, titles and anchor, a score within PRIMARY_SHARE of the best,
        # and a page the router ranks within PAGE_SHARE of the best page (so a weak FAQ page never
        # co-answers, while two fiches with different values both surface as conflicting evidence).
        close = (b.same_rank_class(best) and round(b.title_coverage, 2) >= round(best.title_coverage, 2) - 0.01
                 and b.score >= PRIMARY_SHARE * best.score and b.page_score >= PAGE_SHARE * best.page_score)
        qualifies = b.title_tier >= 1 or bool(b.co_occurrence) or one_term
        if close and qualifies:
            missing = f" (no {b.required_anchor.replace('_', ' ')} on the lines: the typed value is missing)" if not b.anchor_ok else ""
            if b.exact_chapter:
                reason = f"The section title '{b.section_title}' is exactly in the question (every word of it) and the section holds the best lines; covers {_join(b.covered)} ({cov}); score {b.score}: primary."
            elif b.title_tier == 3:
                reason = f"The document '{b.doc_title}' and the section '{b.section_title}' name the question's words {_join(b.covered)} ({cov}); score {b.score}: primary."
            elif b.title_tier >= 1:
                which = f"document '{b.doc_title}'" if b.title_tier == 2 else f"section '{b.section_title}'"
                reason = f"The {which} title names {_join(b.covered)} ({cov}); score {b.score}: primary."
            elif b.co_occurrence:
                reason = f"The {b.co_occurrence} carries {_join(b.covered)} together ({cov}) and the score {b.score} is the highest: primary."
            else:
                reason = f"The question carries one strong word present, {_join(b.covered)}; the lines carry it ({cov}) and the score {b.score} is the highest: primary."
            decisions[b.candidate_id] = Decision("primary", reason[:-1] + missing + ".")
        elif b.co_occurrence or b.title_keywords or b.title_tier >= 1:
            if best.exact_chapter and not b.exact_chapter:
                reason = f"Covers {_join(b.covered)} ({cov}) but the title of {best.candidate_id} ('{best.section_title}') is exactly in the question: supporting (also answered here)."
            elif best.topic_match and not b.topic_match:
                reason = f"Covers {_join(b.covered)} ({cov}) but its page's topic '{b.page_topic or 'none'}' is not the question's '{question_topic}', which {best.candidate_id} is on: supporting."
            elif round(best.coverage, 2) > round(b.coverage, 2):
                reason = f"Covers {_join(b.covered)} ({cov}) but {best.candidate_id} covers more of the question ({best.coverage:.2f}): supporting."
            elif best.title_tier > b.title_tier or (best.title_tier == b.title_tier and best.title_tier >= 1 and best.title_coverage > b.title_coverage + 0.01):
                reason = f"Covers {_join(b.covered)} ({cov}) but {best.candidate_id} is titled with the question's words: supporting (also answered here)."
            elif best.anchor_ok and not b.anchor_ok:
                kind = (b.required_anchor or "").replace("_", " ")
                reason = f"Covers {_join(b.covered)} ({cov}) but carries no {kind}, which an answer of type {answer_type} requires and {best.candidate_id} has: supporting."
            elif best.doc_id != b.doc_id and round(best.page_score, 2) > round(b.page_score, 2):
                reason = f"Covers {_join(b.covered)} ({cov}) but the router ranks the page of {best.candidate_id} first ({best.page_score} vs {b.page_score}): supporting."
            elif not qualifies:
                reason = f"Covers {_join(b.covered)} ({cov}) but only {kws} hits the lines, no title and no second concept: supporting."
            else:
                reason = f"Covers {_join(b.covered)} ({cov}) but the score {b.score} is behind {best.candidate_id}: supporting."
            decisions[b.candidate_id] = Decision("supporting", reason)
        else:
            decisions[b.candidate_id] = Decision("tangential", f"Only {kws} hits these lines: no second concept and no title match.")
    return decisions
