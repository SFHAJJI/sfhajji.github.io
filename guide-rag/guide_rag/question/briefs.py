"""Two views of one parsed question: what retrieval needs and what generation needs.

Retrieval gets keywords, rewrites, anchors and scope, never the reader's original wording: it
filters lines, it does not interpret. Generation gets the original wording, the format constraint
and the disambiguation, never the keyword list: it answers the reader, it does not search.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from guide_rag.question.parse_question import Keyword, ParsedQuestion


class RetrievalScope(BaseModel):
    topic: str | None
    pages_hint: list[str] | None
    toc_section_hint: str | None
    answer_context: str
    answer_shape: str
    answer_type: str
    language: str


class RetrievalBrief(BaseModel):
    question_id: str
    keywords: list[Keyword]  # direct and expert_dictionary, plain text
    rewrites: list[str]  # the corrected question, then its sub-questions
    anchors: list[Keyword]  # the regex keywords
    scope: RetrievalScope


class Disambiguation(BaseModel):
    reason: str
    suggested_clarification: str | None
    candidate_values: list[str]
    proposed_default: str | None


class GenerationBrief(BaseModel):
    question_id: str
    original_question: str
    language: str
    answer_shape: str
    answer_type: str
    format_constraint: str
    sub_questions: list[str] = Field(default_factory=list)
    disambiguation: Disambiguation | None = None


_FORMAT: dict[str, str] = {
    "text": "one short text item, verbatim from the cited lines",
    "amount": "one amount with its currency or unit, taken from the cited line",
    "date": "one date in ISO form with the original wording, taken from the cited line",
    "boolean": "yes or no, with the line that says so",
    "address": "one address, verbatim from the cited lines",
    "phone": "one telephone number, verbatim from the cited line",
    "url": "one link, verbatim from the cited line",
    "duration": "one duration with its unit, taken from the cited line",
}


def retrieval_brief(parsed: ParsedQuestion) -> RetrievalBrief:
    plain = [k for k in parsed.keywords if not k.is_regex]
    anchors = [k for k in parsed.keywords if k.is_regex]
    rewrites = [parsed.corrected_question] + [s for s in parsed.decomposition.sub_questions if s != parsed.corrected_question]
    hints = parsed.structural_hints
    return RetrievalBrief(
        question_id=parsed.question_id,
        keywords=plain,
        rewrites=rewrites,
        anchors=anchors,
        scope=RetrievalScope(
            topic=parsed.scope_filters.topic,
            pages_hint=hints.pages_hint,
            toc_section_hint=hints.toc_section_hint,
            answer_context=hints.answer_context,
            answer_shape=parsed.answer_shape,
            answer_type=parsed.answer_type,
            language=parsed.language,
        ),
    )


def generation_brief(parsed: ParsedQuestion) -> GenerationBrief:
    constraint = _FORMAT[parsed.answer_type]
    if parsed.answer_shape == "listing":
        constraint = "a list: one item per matching line of the section, each verbatim with its span"
    disambiguation = None
    if parsed.ambiguity_reason is not None:
        disambiguation = Disambiguation(
            reason=parsed.ambiguity_reason,
            suggested_clarification=parsed.suggested_clarification,
            candidate_values=parsed.candidate_values,
            proposed_default=parsed.proposed_default,
        )
    return GenerationBrief(
        question_id=parsed.question_id,
        original_question=parsed.original_question,
        language=parsed.language,
        answer_shape=parsed.answer_shape,
        answer_type=parsed.answer_type,
        format_constraint=constraint,
        sub_questions=list(parsed.decomposition.sub_questions),
        disambiguation=disambiguation,
    )
