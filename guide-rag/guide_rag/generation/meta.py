"""The `_meta` block of SPEC §4: what ran, what was skipped and why, which model, which prompt."""

from __future__ import annotations

from typing import Any

from ..retrieval.contracts import attr, hints, plan_activations
from ..retrieval.result import RetrievalResult
from .schemas import ActivationOut, GenerationMeta, ValidationProblem


def chunk_strategy_of(parsed: Any) -> str:
    _, _, answer_context = hints(parsed)
    context = {"line": "the hit lines", "paragraph": "±3 lines within the section", "section": "the whole section"}
    return f"line as the unit; anchor = hit lines grouped by runs; context = {context.get(answer_context, answer_context)} (answer_context={answer_context})"


def build_meta(parsed: Any, plan: Any, retrieval: RetrievalResult | None, *, index_version: str | None,
               pipeline_version: str, model_used: str = "no model", prompt_version: str | None = None,
               fragments_applied: list[str] | None = None, iterations: int = 1,
               validator_report: dict[str, list[ValidationProblem]] | None = None,
               timings_ms: dict[str, float] | None = None) -> GenerationMeta:
    return GenerationMeta(
        question_id=str(attr(parsed, "question_id", "") or ""),
        index_version=index_version,
        pipeline_version=pipeline_version,
        methods_used=list(retrieval.methods_used) if retrieval else [],
        methods_skipped=dict(retrieval.methods_skipped) if retrieval else {},
        activations={k: ActivationOut(**v) for k, v in plan_activations(plan).items()},
        chunk_strategy=chunk_strategy_of(parsed),
        model_used=model_used,
        prompt_version=prompt_version,
        fragments_applied=list(fragments_applied or []),
        iterations=iterations,
        validator_report=dict(validator_report or {}),
        timings_ms={k: round(float(v), 3) for k, v in (timings_ms or {}).items()},
    )
