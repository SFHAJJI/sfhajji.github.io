"""Anchor -> context (SPEC §3): the hit lines are the anchor, the context is the paragraph (±3 lines
within the section) or the section, per `answer_context`; the context always contains the anchor.

A section's "own lines" run from its heading to the line before its first child heading: the
context of a parent section is its own lines, never its children's (they are sections of their own).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .detectors import LineRecord, _s

PARAGRAPH_RADIUS = 3
RUN_GAP = 2  # hit lines at most this far apart form one anchor run


@dataclass(frozen=True)
class SectionBounds:
    doc_id: str
    section_id: str
    title: str
    breadcrumb: str
    start_line: int
    end_line: int
    anchor_id: str | None
    level: int
    own_end: int  # the last line before the first child heading (end_line for a leaf)


def section_bounds(toc_df: Any, doc_id: str | None = None) -> dict[tuple[str, str], SectionBounds]:
    """(doc_id, section_id) -> bounds, read once from toc_df."""
    out: dict[tuple[str, str], SectionBounds] = {}
    if toc_df is None or len(toc_df) == 0:
        return out
    df = toc_df if doc_id is None else toc_df[toc_df["doc_id"] == doc_id]
    records = df.to_dict("records")
    starts_by_doc: dict[str, list[tuple[int, int]]] = {}
    for r in records:
        starts_by_doc.setdefault(str(r["doc_id"]), []).append((int(r["start_line"]), int(r.get("level", 1) or 1)))
    for r in records:
        d, start, end, level = str(r["doc_id"]), int(r["start_line"]), int(r["end_line"]), int(r.get("level", 1) or 1)
        inner = [s for s, lv in starts_by_doc[d] if start < s <= end and lv > level]
        b = SectionBounds(
            doc_id=d,
            section_id=str(r["section_id"]),
            title=_s(r.get("title")),
            breadcrumb=_s(r.get("breadcrumb")) or _s(r.get("title")),
            start_line=start,
            end_line=end,
            anchor_id=_s(r.get("anchor_id")) or None,
            level=level,
            own_end=min(inner) - 1 if inner else end,
        )
        out[(b.doc_id, b.section_id)] = b
    return out


def anchor_runs(line_nums: Iterable[int], gap: int = RUN_GAP) -> list[tuple[int, int]]:
    """Group hit lines into runs: lines closer than `gap` belong to one anchor ("anchor small")."""
    nums = sorted(set(int(n) for n in line_nums))
    runs: list[tuple[int, int]] = []
    for n in nums:
        if runs and n - runs[-1][1] <= gap:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def context_for(anchor: tuple[int, int], bounds: SectionBounds | None, answer_context: str,
                page_last_line: int | None = None) -> tuple[int, int]:
    """The context range for an anchor; clipped to the section's own lines (or the page when no section)."""
    a_start, a_end = anchor
    lo = bounds.start_line if bounds else 1
    hi = bounds.own_end if bounds else (page_last_line or a_end)
    if answer_context == "line":
        c = (a_start, a_end)
    elif answer_context == "section":
        c = (lo, hi)
    else:  # paragraph: ±3 lines within the section
        c = (max(lo, a_start - PARAGRAPH_RADIUS), min(hi, a_end + PARAGRAPH_RADIUS))
    # The invariant of rule 5: the context contains the anchor, whatever the clipping did.
    c = (min(c[0], a_start), max(c[1], a_end))
    return c


def contains(context: tuple[int, int], anchor: tuple[int, int]) -> bool:
    return context[0] <= anchor[0] and anchor[1] <= context[1]


def lines_in(lines: list[LineRecord], doc_id: str, start: int, end: int) -> list[LineRecord]:
    return [l for l in lines if l.doc_id == doc_id and start <= l.line_num <= end]


def is_whole_section(context: tuple[int, int], bounds: SectionBounds | None) -> bool:
    """True when the context is the section's own lines (heading to the line before its first child)."""
    return bounds is not None and context[0] <= bounds.start_line and context[1] >= bounds.own_end
