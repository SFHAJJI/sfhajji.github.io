"""The deterministic dispatcher: one `ExecutionPlan` per parsed question, every flag with a reason.

SPEC §0 rule 7: same question, same route. Nothing here reads the corpus text; it reads the
parsed question and the shape of the tables (how many sections, which table columns exist).
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel

from guide_rag.question.normalize import fold
from guide_rag.question.parse_question import AnswerContext, ParsedQuestion

MIN_TOC_SECTIONS = 3
EMBEDDINGS_OFF_REASON = "no vocabulary mismatch expected beyond the dictionary; keywords prove absence"


class Activation(BaseModel):
    on: bool
    reason: str


class ExecutionPlan(BaseModel):
    question_id: str
    use_keywords: Activation
    use_toc: Activation
    use_row_level: Activation
    use_embeddings: Activation
    use_llm_arbiter: Activation
    use_llm_generation: Activation
    sweep_for_absence: Activation
    current_page_boost: Activation
    answer_context: AnswerContext
    answer_context_reason: str
    chunk_strategy: Literal["sequential", "combined"]
    chunk_strategy_reason: str

    def activations(self) -> dict[str, dict[str, object]]:
        """The `_meta.activations` block: {flag: {on, reason}}."""
        return {
            name: {"on": value["on"], "reason": value["reason"]}
            for name, value in self.model_dump().items()
            if isinstance(value, dict) and "on" in value
        }

    @property
    def methods_planned(self) -> list[str]:
        return [name for name, a in self.activations().items() if a["on"]]


def _named_table_column(parsed: ParsedQuestion, row_df: pd.DataFrame | None) -> str | None:
    """A keyword that is also a column header of some table, else None."""
    if row_df is None or len(row_df) == 0 or "column_headers" not in row_df.columns:
        return None
    headers: set[str] = set()
    for value in row_df["column_headers"]:
        if isinstance(value, str):
            parts = value.split("|")
        else:
            try:
                parts = list(value)
            except TypeError:
                parts = []
        headers.update(fold(str(p).strip()) for p in parts if str(p).strip())
    for keyword in parsed.keywords:
        if keyword.is_regex:
            continue
        if fold(keyword.text) in headers:
            return keyword.text
    return None


def dispatch(
    parsed: ParsedQuestion,
    *,
    toc_df: pd.DataFrame | None,
    llm_available: bool = False,
    row_df: pd.DataFrame | None = None,
) -> ExecutionPlan:
    """Decide every retrieval and generation method from the parsed question alone."""
    n_sections = 0 if toc_df is None else len(toc_df)
    shape, atype = parsed.answer_shape, parsed.answer_type

    use_toc = n_sections >= MIN_TOC_SECTIONS
    column = _named_table_column(parsed, row_df)
    if atype in ("amount", "date"):
        row_level = Activation(on=True, reason=f"answer_type={atype}: tables carry typed values")
    elif column is not None:
        row_level = Activation(on=True, reason=f"the question names the table column '{column}'")
    else:
        row_level = Activation(on=False, reason=f"answer_type={atype} and no table column named")

    if shape == "listing":
        context: AnswerContext = "section"
        context_reason = "listing: the whole section is the answer"
        chunk, chunk_reason = "combined", "listing: the section's lines are read together, one item per line"
    elif atype in ("amount", "date", "boolean", "phone", "url", "duration"):
        context, context_reason = "line", f"{atype}: a typed value sits on one line"
        chunk, chunk_reason = "sequential", "single typed value: candidates are tried one by one, best first"
    else:
        context, context_reason = "paragraph", f"single {atype}: the paragraph around the anchor"
        chunk, chunk_reason = "sequential", "single text answer: candidates are tried one by one, best first"

    pages = parsed.structural_hints.pages_hint
    return ExecutionPlan(
        question_id=parsed.question_id,
        use_keywords=Activation(on=True, reason="always: keyword detectors are deterministic and prove absence"),
        use_toc=Activation(
            on=use_toc,
            reason=(
                f"toc_df has {n_sections} sections (>= {MIN_TOC_SECTIONS}): headings are a first-class signal"
                if use_toc
                else f"toc_df has {n_sections} sections (< {MIN_TOC_SECTIONS}): too few headings to route by"
            ),
        ),
        use_row_level=row_level,
        use_embeddings=Activation(on=False, reason=EMBEDDINGS_OFF_REASON),
        use_llm_arbiter=Activation(
            on=llm_available, reason="a model key is configured" if llm_available else "no model key configured"
        ),
        use_llm_generation=Activation(
            on=llm_available, reason="a model key is configured" if llm_available else "no model key configured"
        ),
        sweep_for_absence=Activation(on=True, reason="always: the exhaustive sweep is the evidence of absence"),
        current_page_boost=Activation(
            on=bool(pages),
            reason=f"pages_hint={pages}: the reader's page gets x1.3" if pages else "no pages_hint: no page to boost",
        ),
        answer_context=context,
        answer_context_reason=context_reason,
        chunk_strategy=chunk,  # type: ignore[arg-type]
        chunk_strategy_reason=chunk_reason,
    )
