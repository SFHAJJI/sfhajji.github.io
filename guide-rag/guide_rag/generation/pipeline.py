"""`answer_question`: retrieve -> verbatim (or the model) -> validate (one retry with discovered
keywords, then a typed not-answered) -> absence when nothing was found. `replay` re-runs a trace.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..retrieval.contracts import (ExecutionPlan, Keyword, ParsedQuestion, as_tables, attr, concept_variants,
                                   plan_activation, plan_activations, question_terms)
from ..retrieval.detectors import line_records
from ..retrieval.result import RetrievalResult, retrieve
from ..retrieval.text import contains_keyword, fold
from .absence import build_absence
from .meta import build_meta
from .schemas import AbsenceJustification, AnswerBase, GenerationResult, Trace, expected_kind
from .validator import validate
from .verbatim import generate_verbatim, not_answered

PIPELINE_VERSION = "guide-rag/0.1"
MAX_DISCOVERED = 5


def _dump(obj: Any) -> dict:
    """A plain dict of a pydantic model, a dataclass, a mapping or a namespace."""
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return json.loads(json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o))))
    if hasattr(obj, "__dict__"):
        return json.loads(json.dumps(vars(obj), default=lambda o: getattr(o, "__dict__", str(o))))
    return {}


def to_parsed(parsed: Any) -> ParsedQuestion:
    """The duck-typed question as the contract model, so it can be copied with more keywords and traced."""
    if isinstance(parsed, ParsedQuestion):
        return parsed
    data = _dump(parsed)
    data.setdefault("question_id", str(attr(parsed, "question_id", "") or ""))
    data.setdefault("original_question", str(attr(parsed, "original_question", "") or ""))
    data.setdefault("corrected_question", str(attr(parsed, "corrected_question", data["original_question"]) or ""))
    return ParsedQuestion.model_validate(data)


def to_plan(plan: Any) -> ExecutionPlan:
    if isinstance(plan, ExecutionPlan):
        return plan
    return ExecutionPlan(activations=plan_activations(plan))


def discovered_keywords(answer: AnswerBase | None, parsed: Any, retrieval: RetrievalResult, tables: Any, dictionary: Any) -> list[Keyword]:
    """Keywords for the retry: what the model proposed, plus dictionary variants of the question's
    concepts that occur in the primaries' context but are not yet in the question."""
    have = {fold(t.text) for t in question_terms(parsed)}
    found: list[Keyword] = []
    for text in (answer.llm_discovered_keywords if answer is not None else []):
        if fold(text) not in have:
            have.add(fold(text))
            found.append(Keyword(text=text, weight=0.6, source="expert_dictionary", concept=None))
    by_concept = concept_variants(dictionary, parsed)
    q_concepts = set(retrieval.question_concepts)
    t = as_tables(tables)
    lines = line_records(t.line_df, {c.context.doc_id for c in retrieval.candidates if c.role != "discarded"})
    texts = [l.text for c in retrieval.candidates if c.role != "discarded" for l in lines
             if l.doc_id == c.context.doc_id and c.context.line_start <= l.line_num <= c.context.line_end]
    for concept in sorted(q_concepts):
        for v in by_concept.get(concept, []):
            if fold(v) in have or len(found) >= MAX_DISCOVERED:
                continue
            if any(contains_keyword(x, v) for x in texts):
                have.add(fold(v))
                found.append(Keyword(text=v, weight=0.6, source="expert_dictionary", concept=concept))
    return found[:MAX_DISCOVERED]


def answer_question(parsed: Any, plan: Any, tables: Any, dictionary: Any = None, *, llm_client: Any = None,
                    index_version: str | None = None) -> GenerationResult:
    timings: dict[str, float] = {}
    t = as_tables(tables)
    index_version = index_version or t.index_version
    pq = to_parsed(parsed)
    plan_model = to_plan(plan)
    use_llm, _ = plan_activation(plan_model, "use_llm_generation")
    model_used, prompt_version, fragments = "no model", None, []

    def generate(retr: RetrievalResult) -> AnswerBase:
        nonlocal model_used, prompt_version, fragments
        if use_llm and llm_client is not None and retr.primaries:
            from .llm import generate_with_llm  # imported here so the no-model path never needs httpx

            answer, info = generate_with_llm(pq, retr, t, llm_client)
            model_used, prompt_version, fragments = info.model_used, info.prompt_version, info.fragments_applied
            return answer
        return generate_verbatim(pq, retr, t)

    t0 = time.perf_counter()
    retrieval = retrieve(pq, plan_model, t, dictionary)
    timings["retrieval"] = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    answer = generate(retrieval)
    timings["generation"] = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    report = {"iteration_1": validate(answer, t.line_df, pq)}
    iterations = 1
    if report["iteration_1"]:
        # One retry with the discovered keywords; then the typed not-answered. What fails is not shipped.
        extra = discovered_keywords(answer, pq, retrieval, t, dictionary)
        pq2 = pq.model_copy(update={"keywords": list(pq.keywords) + extra}) if extra else pq
        retrieval = retrieve(pq2, plan_model, t, dictionary)
        answer = generate(retrieval)
        report["iteration_2"] = validate(answer, t.line_df, pq)
        iterations = 2
        if report["iteration_2"]:
            kind = expected_kind(pq.answer_shape, pq.answer_type)
            answer = not_answered(kind, retrieval, ["Rejected by the validator: " + "; ".join(p.message for p in report["iteration_2"])])
    timings["validation"] = (time.perf_counter() - t2) * 1000

    final: Any = answer
    if retrieval.not_found and not answer.items:
        t3 = time.perf_counter()
        final = build_absence(pq, retrieval, t, dictionary, index_version=index_version, pipeline_version=PIPELINE_VERSION)
        timings["absence"] = (time.perf_counter() - t3) * 1000
    timings["total"] = (time.perf_counter() - t0) * 1000

    meta = build_meta(pq, plan_model, retrieval, index_version=index_version, pipeline_version=PIPELINE_VERSION,
                      model_used=model_used, prompt_version=prompt_version, fragments_applied=fragments,
                      iterations=iterations, validator_report=report, timings_ms=timings)
    return GenerationResult(answer=final, meta=meta, trace=Trace(parsed=pq.model_dump(mode="json"), plan=plan_model.model_dump(mode="json"), retrieval=retrieval))


def replay(trace_json: str | dict, tables: Any, dictionary: Any = None, llm_client: Any = None) -> GenerationResult:
    """Re-run a saved GenerationResult (its JSON) and record whether the same candidates and spans came back."""
    data = json.loads(trace_json) if isinstance(trace_json, str) else trace_json
    trace = data.get("trace") or {}
    parsed = ParsedQuestion.model_validate(trace["parsed"])
    plan = ExecutionPlan.model_validate(trace["plan"])
    index_version = (data.get("meta") or {}).get("index_version")
    result = answer_question(parsed, plan, tables, dictionary, llm_client=llm_client, index_version=index_version)
    old_ids = [c["candidate_id"] for c in (trace.get("retrieval") or {}).get("candidates", [])]
    new_ids = [c.candidate_id for c in result.trace.retrieval.candidates] if result.trace else []
    old_answer = data.get("answer") or {}
    old_spans = [s for it in old_answer.get("items", []) for s in it.get("spans", [])]
    new_spans = [] if isinstance(result.answer, AbsenceJustification) else [s.model_dump() for it in result.answer.items for s in it.spans]
    result.meta.replay = {
        "source_question_id": parsed.question_id,
        "candidates_identical": old_ids == new_ids,
        "spans_identical": old_spans == new_spans,
        "index_version_identical": index_version == result.meta.index_version,
    }
    return result
