"""The no-model generator of SPEC §4: the primary candidate's anchor lines become the item(s),
verbatim; typed values come from the regex captures with the line as their span.
"""

from __future__ import annotations

from typing import Any

from ..retrieval.contracts import as_tables, attr, question_terms
from ..retrieval.detectors import LineRecord, line_records
from ..retrieval.result import RetrievalResult, RetrievedCandidate
from ..retrieval.scope import is_whole_section, section_bounds
from ..retrieval.text import phrase_in, stems
from .schemas import (ANSWER_CLASSES, Amount, AmountItem, AnswerBase, BooleanItem, ConflictingEvidence,
                      ContextBlock, DateItem, DateValue, Span, TextItem, expected_kind)

MAX_LIST_ITEMS = 30
PARTIAL_CONFIDENCE_CAP = 0.6
NEGATIONS = {"pas", "ne", "non", "aucun", "aucune", "jamais", "interdit", "interdite", "not", "no", "never",
             "nicht", "kein", "keine", "nie"}
CAPTURE_KINDS = {"amount": {"amount", "duration"}, "date": {"date"}}


def context_blocks(candidates: list[RetrievedCandidate]) -> list[ContextBlock]:
    return [
        ContextBlock(candidate_id=c.candidate_id, doc_id=c.context.doc_id, section_id=c.context.section_id,
                     section_title=c.section_title, breadcrumb=c.breadcrumb, line_start=c.context.line_start,
                     line_end=c.context.line_end, url_anchor=c.url_anchor, role=c.role)
        for c in candidates
    ]


def not_answered(kind: str, retrieval: RetrievalResult | None, caveats: list[str]) -> AnswerBase:
    """The typed not-answered answer: the right class, no item, both booleans false."""
    cls = ANSWER_CLASSES[kind]
    return cls(items=[], extraction_method="na", confidence=0.0, caveats=list(caveats), answer_found=False,
               complete_answer_found=False, context_structured=context_blocks(retrieval.primaries) if retrieval else [],
               keywords_found=sorted({k for c in (retrieval.primaries if retrieval else []) for k in c.matched_keywords}))


def _lines(lines: list[LineRecord], doc_id: str, start: int, end: int) -> list[LineRecord]:
    return [l for l in lines if l.doc_id == doc_id and start <= l.line_num <= end]


def _fmt_amount(cap: dict) -> str:
    value = cap["value"]
    v = f"{value:g}"
    return " ".join(x for x in (v, cap.get("currency") or "", cap.get("unit") or "") if x)


def _typed_items(primaries: list[RetrievedCandidate], kind: str, lines: list[LineRecord]) -> tuple[list, list[ConflictingEvidence], list[str]]:
    """Typed items from the first primary's captures; other pages with other values are conflicts."""
    wanted = CAPTURE_KINDS[kind]
    items: list = []
    conflicts: list[ConflictingEvidence] = []
    caveats: list[str] = []
    seen_values: set[str] = set()

    def values_of(c: RetrievedCandidate) -> list[tuple[str, dict]]:
        out = []
        for cap in c.captures:
            if cap.get("kind") in wanted:
                key = cap["iso"] if kind == "date" else _fmt_amount(cap)
                out.append((key, cap))
        return out

    def item_of(c: RetrievedCandidate, cap: dict):
        line = next((l for l in _lines(lines, c.anchor.doc_id, cap["line_num"], cap["line_num"])), None)
        span = Span(doc_id=c.anchor.doc_id, line_start=cap["line_num"], line_end=cap["line_num"], quote=line.text if line else None)
        if kind == "date":
            return DateItem(date=DateValue(iso=cap["iso"], original=cap["original"]), spans=[span])
        return AmountItem(amount=Amount(value=cap["value"], currency=cap.get("currency"), unit=cap.get("unit")), spans=[span])

    first = primaries[0]
    first_values = values_of(first)
    for key, cap in first_values:
        if key not in seen_values:
            seen_values.add(key)
            items.append(item_of(first, cap))
    if not first_values:
        caveats.append(f"No {kind} on the primary lines {first.candidate_id}; nothing typed could be extracted.")
    for other in primaries[1:]:
        vals = values_of(other)
        if not vals:
            continue
        keys = {k for k, _ in vals}
        if other.anchor.doc_id != first.anchor.doc_id and keys != {k for k, _ in first_values}:
            conflicts.append(ConflictingEvidence(
                candidate_ids=[first.candidate_id, other.candidate_id],
                values=[", ".join(sorted({k for k, _ in first_values})) or "none", ", ".join(sorted(keys))],
                note=f"{first.breadcrumb or first.anchor.doc_id} and {other.breadcrumb or other.anchor.doc_id} carry different values.",
            ))
            caveats.append(f"Conflicting value on {other.anchor.doc_id} ({other.candidate_id}): {', '.join(sorted(keys))}.")
        elif other.anchor.doc_id == first.anchor.doc_id:
            for key, cap in vals:
                if key not in seen_values:
                    seen_values.add(key)
                    items.append(item_of(other, cap))
    return items, conflicts, caveats


def _list_items(primaries: list[RetrievedCandidate], lines: list[LineRecord], parsed: Any, bounds: dict | None = None) -> list[TextItem]:
    """One item per list item / matching line of each primary's context (the section for listings);
    when the section has child sections, their headings are items too (the steps of a procedure)."""
    term_stems = [stems(t.text) for t in question_terms(parsed) if not t.is_regex and stems(t.text)]
    items: list[TextItem] = []
    seen: set[tuple[str, int]] = set()
    for c in primaries:
        ctx = _lines(lines, c.context.doc_id, c.context.line_start, c.context.line_end)
        picked = [l for l in ctx if not l.is_heading and (l.element in ("li", "td", "dd") or any(phrase_in(ps, l.stems) for ps in term_stems))]
        b = (bounds or {}).get((c.context.doc_id, c.context.section_id or ""))
        if b is not None and b.own_end < b.end_line:
            children = [x for (d, _), x in (bounds or {}).items() if d == b.doc_id and b.start_line < x.start_line <= b.end_line and x.level == b.level + 1]
            picked += [l for x in sorted(children, key=lambda x: x.start_line) for l in _lines(lines, x.doc_id, x.start_line, x.start_line)]
        if not picked:
            picked = _lines(lines, c.anchor.doc_id, c.anchor.line_start, c.anchor.line_end)
        for l in picked:
            if (l.doc_id, l.line_num) in seen or len(items) >= MAX_LIST_ITEMS:
                continue
            seen.add((l.doc_id, l.line_num))
            items.append(TextItem(text=l.text, spans=[Span(doc_id=l.doc_id, line_start=l.line_num, line_end=l.line_num, quote=l.text)]))
    return items


def _negated(text: str) -> bool:
    return any(tok in NEGATIONS for tok in stems(text)) or any(tok in NEGATIONS for tok in text.lower().split())


def generate_verbatim(parsed: Any, retrieval: RetrievalResult, tables: Any) -> AnswerBase:
    kind = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"))
    primaries = retrieval.primaries
    if not primaries:
        return not_answered(kind, retrieval, [retrieval.not_found_reason or "no primary candidate"])
    t = as_tables(tables)
    lines = line_records(t.line_df, {c.anchor.doc_id for c in primaries})
    bounds = section_bounds(t.toc_df)
    first = primaries[0]
    caveats: list[str] = []
    conflicts: list[ConflictingEvidence] = []
    extraction = "verbatim"
    items: list = []

    if kind == "list":
        items = _list_items(primaries, lines, parsed, bounds)
        complete = is_whole_section((first.context.line_start, first.context.line_end), bounds.get((first.context.doc_id, first.context.section_id or "")))
    elif kind in ("amount", "date"):
        items, conflicts, caveats = _typed_items(primaries, kind, lines)
        extraction = "computed"  # the value is normalised (1 500 -> 1500.0, 15 janvier 2025 -> ISO)
        complete = bool(items)
    elif kind == "boolean":
        # The item quotes the one sentence that answers: the anchor line carrying most question terms.
        anchor_lines = _lines(lines, first.anchor.doc_id, first.anchor.line_start, first.anchor.line_end)
        term_stems = [stems(x.text) for x in question_terms(parsed) if not x.is_regex and stems(x.text)]
        best = max(anchor_lines, key=lambda l: (sum(1 for ps in term_stems if phrase_in(ps, l.stems)), -l.line_num))
        text = best.text
        value = not _negated(text)
        items = [BooleanItem(boolean=value, spans=[Span(doc_id=best.doc_id, line_start=best.line_num, line_end=best.line_num, quote=text)])]
        extraction = "inferred"
        caveats.append("No model: the boolean is a negation heuristic over the quoted lines; read the quote.")
        for other in primaries[1:]:
            o_lines = _lines(lines, other.anchor.doc_id, other.anchor.line_start, other.anchor.line_end)
            o_value = not _negated(" ".join(l.text for l in o_lines))
            if other.anchor.doc_id != first.anchor.doc_id and o_value != value:
                conflicts.append(ConflictingEvidence(candidate_ids=[first.candidate_id, other.candidate_id], values=[str(value), str(o_value)],
                                                     note=f"{first.breadcrumb} and {other.breadcrumb} read differently."))
        complete = bool(items)
    else:
        # A section context (a procedure) quotes the section's lines; otherwise the anchor lines.
        # Leading heading lines are left out of the quote: the breadcrumb already names them.
        if retrieval.answer_context_used == "section":
            span_lines = _lines(lines, first.context.doc_id, first.context.line_start, first.context.line_end)
            while len(span_lines) > 1 and span_lines[0].is_heading and span_lines[0].line_num < first.anchor.line_start:
                span_lines = span_lines[1:]
        else:
            span_lines = _lines(lines, first.anchor.doc_id, first.anchor.line_start, first.anchor.line_end)
        text = " ".join(l.text for l in span_lines)
        items = [TextItem(text=text, spans=[Span(doc_id=first.anchor.doc_id, line_start=span_lines[0].line_num, line_end=span_lines[-1].line_num, quote=text)])]
        for other in primaries[1:]:
            if other.anchor.doc_id != first.anchor.doc_id:
                caveats.append(f"Also found on {other.anchor.doc_id}: {other.breadcrumb} ({other.candidate_id}).")
        complete = is_whole_section((first.context.line_start, first.context.line_end), bounds.get((first.context.doc_id, first.context.section_id or "")))

    if not complete and items:
        b = bounds.get((first.context.doc_id, first.context.section_id or ""))
        where = f"'{first.breadcrumb or first.section_title}'" if (first.breadcrumb or first.section_title) else first.anchor.doc_id
        span_note = f" (the section spans lines {b.start_line}-{b.end_line})" if b else ""
        caveats.append(f"The context covers lines {first.context.line_start}-{first.context.line_end} of {where}{span_note}, not the whole section.")

    # A partial answer never claims more than 0.6, whatever the retrieval margin said.
    confidence = retrieval.confidence if (items and complete) else min(retrieval.confidence, PARTIAL_CONFIDENCE_CAP)
    cls = ANSWER_CLASSES[kind]
    return cls(
        items=items,
        extraction_method=extraction if items else "na",
        confidence=confidence,
        caveats=caveats,
        answer_found=bool(items),
        complete_answer_found=bool(items) and complete,
        context_structured=context_blocks(primaries),
        keywords_found=sorted({k for c in primaries for k in c.matched_keywords}),
        conflicting_evidence=conflicts,
    )
