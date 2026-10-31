"""The validator of SPEC §4: every span and quote is checked before anything is shown.

`validate(answer, context_lines, parsed)` returns the list of problems; an empty list is a pass.
`context_lines` is line_df (doc_id, line_num, text), a {(doc_id, line_num): text} mapping, or a list
of records with those fields.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Mapping

from ..retrieval.contracts import attr
from ..retrieval.text import squash
from .schemas import AbsenceJustification, DateItem, ValidationProblem, expected_kind

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def line_lookup(context_lines: Any) -> dict[tuple[str, int], str]:
    """(doc_id, line_num) -> text, whatever shape the context came in."""
    if context_lines is None:
        return {}
    if isinstance(context_lines, Mapping):
        return {(str(k[0]), int(k[1])): squash(v) for k, v in context_lines.items()}
    if hasattr(context_lines, "to_dict") and hasattr(context_lines, "columns"):
        records = context_lines.to_dict("records")
    else:
        records = list(context_lines)
    out: dict[tuple[str, int], str] = {}
    for r in records:
        out[(str(attr(r, "doc_id")), int(attr(r, "line_num")))] = squash(attr(r, "text", ""))
    return out


def validate(answer: Any, context_lines: Any, parsed: Any) -> list[ValidationProblem]:
    problems: list[ValidationProblem] = []
    if isinstance(answer, AbsenceJustification):
        if answer.answer is not None:
            problems.append(ValidationProblem(code="absence_with_answer", message="an absence carries no answer"))
        return problems

    kind = str(getattr(answer, "kind", ""))
    expected = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"))
    if kind != expected:
        problems.append(ValidationProblem(code="shape_mismatch", message=f"answer kind {kind} but the question asks for {expected}"))
    items = list(getattr(answer, "items", []) or [])
    if bool(items) != bool(answer.answer_found):
        problems.append(ValidationProblem(code="found_flag", message=f"answer_found={answer.answer_found} but {len(items)} item(s)"))
    if answer.complete_answer_found and not answer.answer_found:
        problems.append(ValidationProblem(code="complete_without_found", message="complete_answer_found without answer_found"))

    lookup = line_lookup(context_lines)
    for i, item in enumerate(items):
        spans = list(getattr(item, "spans", []) or [])
        if not spans:
            problems.append(ValidationProblem(code="missing_span", message="an item has no span", item_index=i))
        for j, span in enumerate(spans):
            if span.line_end < span.line_start:
                problems.append(ValidationProblem(code="span_order", message=f"line_end {span.line_end} < line_start {span.line_start}", item_index=i, span_index=j))
                continue
            missing = [n for n in range(span.line_start, span.line_end + 1) if (span.doc_id, n) not in lookup]
            if missing:
                problems.append(ValidationProblem(code="span_outside_context", message=f"lines {missing} of {span.doc_id} are not in the context", item_index=i, span_index=j))
                continue
            cited = " ".join(lookup[(span.doc_id, n)] for n in range(span.line_start, span.line_end + 1))
            if span.quote is not None and squash(span.quote) not in cited:
                problems.append(ValidationProblem(code="quote_not_in_lines", message="the quote is not in the cited lines", item_index=i, span_index=j))
            if answer.extraction_method == "verbatim" and not (span.quote and squash(span.quote)):
                problems.append(ValidationProblem(code="verbatim_without_quote", message="a verbatim answer must carry a quote", item_index=i, span_index=j))
        if isinstance(item, DateItem):
            iso = item.date.iso
            ok = bool(_ISO.match(iso))
            if ok:
                try:
                    _dt.date.fromisoformat(iso)
                except ValueError:
                    ok = False
            if not ok:
                problems.append(ValidationProblem(code="date_not_iso", message=f"date {iso!r} is not an ISO calendar date", item_index=i))
    return problems
