""""Not in this guide" (SPEC §4 absence.py): the justification built from the sweep, the coverage and
the closest mentions, each with a why_not sentence.
"""

from __future__ import annotations

from typing import Any

from ..retrieval.arbiter import title_concepts
from ..retrieval.contracts import as_tables, attr, concept_variants
from ..retrieval.result import RetrievalResult
from ..retrieval.scope import section_bounds
from ..retrieval.text import concept_label
from .schemas import AbsenceJustification, ConceptSearch, Mention, ParseCoverage

MAX_MENTIONS = 5


def coverage_of(tables: Any, index_version: str | None = None, pipeline_version: str | None = None) -> ParseCoverage:
    """The coverage JSON when brick 1 wrote one, else counts computed from the tables."""
    t = as_tables(tables)
    if t.parse_coverage:
        data = dict(t.parse_coverage)
        data.setdefault("index_version", index_version or t.index_version)
        data.setdefault("pipeline_version", pipeline_version)
        return ParseCoverage.model_validate(data)
    line_df, toc_df, row_df, page_df = t.line_df, t.toc_df, t.row_df, t.page_df
    docs = set(line_df["doc_id"].tolist()) if line_df is not None and len(line_df) else set()
    pages_total = len(page_df) if page_df is not None and len(page_df) else len(docs)
    return ParseCoverage(
        pages_total=pages_total,
        pages_with_text=len(docs),
        lines_total=int(len(line_df)) if line_df is not None else 0,
        sections_total=int(len(toc_df)) if toc_df is not None else 0,
        tables_total=int(row_df["table_id"].nunique()) if row_df is not None and len(row_df) and "table_id" in row_df.columns else 0,
        cross_refs=int(len(t.cross_ref_df)) if t.cross_ref_df is not None else 0,
        index_version=index_version or t.index_version,
        pipeline_version=pipeline_version,
    )


def innermost_title(bounds: dict, doc_id: str, line_num: int) -> str:
    """The title of the deepest section containing the line (sections nest, so the deepest level wins)."""
    containing = [b for (d, _), b in bounds.items() if d == doc_id and b.start_line <= line_num <= b.end_line]
    if not containing:
        return ""
    return max(containing, key=lambda b: (b.level, b.start_line)).title


def _why_not(doc_id: str, section_title: str, concept: str, question_concepts: list[str],
             variants_by_concept: dict[str, list[str]], reason: str | None = None) -> str:
    named = [c for c in title_concepts(section_title, variants_by_concept) if c not in question_concepts]
    if named:
        return f"names {concept_label(concept)} in the '{section_title}' section, which is about {concept_label(named[0])}"
    if reason:
        return reason
    where = f"the '{section_title}' section" if section_title else f"page {doc_id}"
    return f"names {concept_label(concept)} in {where} without the other concept(s) of the question"


def build_absence(parsed: Any, retrieval: RetrievalResult, tables: Any, dictionary: Any = None, *,
                  index_version: str | None = None, pipeline_version: str | None = None) -> AbsenceJustification:
    t = as_tables(tables)
    variants_by_concept = concept_variants(dictionary, parsed)
    q_concepts = list(retrieval.question_concepts)
    searched = [ConceptSearch(concept=c.concept, variants=c.variants, pages_with_hits=c.pages_with_hits, line_hits=c.line_hits)
                for c in retrieval.sweep_concepts]
    hit_counts = {c.concept: c.line_hits for c in searched}
    # Every word the best candidate left uncovered is a searched concept of its own (0 hits when the
    # sweep never saw it), so the reader sees each word that was looked for.
    terms_by_text = {str(x.get("text")): x for x in retrieval.terms}
    for word in retrieval.uncovered_words:
        key = str(terms_by_text.get(word, {}).get("concept_key") or word)
        if key not in hit_counts and word not in hit_counts:
            searched.append(ConceptSearch(concept=word, variants=[word], pages_with_hits=[], line_hits=0))
            hit_counts[word] = 0

    # The reason: a vague question first, then "never mentioned", then "mentioned but off topic".
    ambiguity = attr(parsed, "ambiguity_reason")
    if ambiguity:
        reason = "ambiguous_question"
    elif not searched or any(n == 0 for n in hit_counts.values()):
        reason = "concept_not_found"
    else:
        reason = "concept_found_but_off_topic"

    # Closest mentions: the non-primary candidates first (they carry the arbiter's sentence), then the
    # sweep rows not already shown.
    bounds = section_bounds(t.toc_df)
    mentions: list[Mention] = []
    seen: set[tuple[str, int]] = set()
    for c in retrieval.candidates:
        if c.role == "primary":
            continue
        key = (c.anchor.doc_id, c.anchor.line_start)
        if key in seen:
            continue
        seen.add(key)
        concept = c.matched_concepts[0] if c.matched_concepts else (c.matched_keywords[0] if c.matched_keywords else "the term")
        mentions.append(Mention(doc_id=c.anchor.doc_id, line_num=c.anchor.line_start, snippet=c.snippet,
                                why_not_an_answer=_why_not(c.anchor.doc_id, c.section_title, concept, q_concepts, variants_by_concept, c.reason)))
    for r in retrieval.sweep_rows:
        if len(mentions) >= MAX_MENTIONS:
            break
        key = (r.doc_id, r.line_num)
        if key in seen:
            continue
        seen.add(key)
        title = innermost_title(bounds, r.doc_id, r.line_num)
        mentions.append(Mention(doc_id=r.doc_id, line_num=r.line_num, snippet=r.snippet,
                                why_not_an_answer=_why_not(r.doc_id, title, r.concept, q_concepts, variants_by_concept)))
    mentions = mentions[:MAX_MENTIONS]

    suggestion = attr(parsed, "proposed_default") or attr(parsed, "suggested_clarification")
    if not suggestion:
        missing = [c for c, n in hit_counts.items() if n == 0]
        present = [c for c, n in hit_counts.items() if n > 0]
        if missing and present:
            suggestion = f"The guide never mentions {', '.join(concept_label(c) for c in missing)}; it does cover {', '.join(concept_label(c) for c in present)}: ask about that."
        elif missing:
            suggestion = f"The guide never mentions {', '.join(concept_label(c) for c in missing)}; try another wording or another topic of the guide."
        elif mentions:
            pages = sorted({m.doc_id for m in mentions})
            suggestion = f"The terms appear on {', '.join(pages)} but in sections about something else; ask about those sections directly."
        else:
            suggestion = "Try another wording or another topic of the guide."

    return AbsenceJustification(
        reason=reason,
        searched_concepts=searched,
        closest_mentions=mentions,
        parse_coverage=coverage_of(t, index_version, pipeline_version),
        suggestion=suggestion,
        suggested_clarification=attr(parsed, "suggested_clarification"),
    )
