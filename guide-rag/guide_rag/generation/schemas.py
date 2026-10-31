"""The typed answer of SPEC §4. Every item carries spans; the two booleans sit on every answer."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from ..retrieval.result import RetrievalResult

ExtractionMethod = Literal["verbatim", "computed", "inferred", "na"]
AbsenceReason = Literal["concept_not_found", "concept_found_but_off_topic", "ambiguous_question"]


class Span(BaseModel):
    doc_id: str
    line_start: int
    line_end: int
    quote: str | None = None


class Amount(BaseModel):
    value: float
    currency: str | None = None
    unit: str | None = None


class DateValue(BaseModel):
    iso: str
    original: str


class TextItem(BaseModel):
    text: str
    spans: list[Span] = Field(default_factory=list)


class AmountItem(BaseModel):
    amount: Amount
    spans: list[Span] = Field(default_factory=list)


class DateItem(BaseModel):
    date: DateValue
    spans: list[Span] = Field(default_factory=list)


class BooleanItem(BaseModel):
    boolean: bool
    spans: list[Span] = Field(default_factory=list)


class ContextBlock(BaseModel):
    """Where an answer comes from: the structural address of a primary candidate."""

    candidate_id: str
    doc_id: str
    section_id: str | None = None
    section_title: str = ""
    breadcrumb: str = ""
    line_start: int
    line_end: int
    url_anchor: str | None = None
    role: str = "primary"


class ConflictingEvidence(BaseModel):
    candidate_ids: list[str]
    values: list[str]
    note: str


class AnswerBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extraction_method: ExtractionMethod = "na"
    confidence: float = 0.0
    caveats: list[str] = Field(default_factory=list)
    answer_found: bool = False
    complete_answer_found: bool = False
    context_structured: list[ContextBlock] = Field(default_factory=list)
    keywords_found: list[str] = Field(default_factory=list)
    llm_discovered_keywords: list[str] = Field(default_factory=list)
    conflicting_evidence: list[ConflictingEvidence] = Field(default_factory=list)
    suggested_clarification: str | None = None


class TextAnswer(AnswerBase):
    kind: Literal["text"] = "text"
    items: list[TextItem] = Field(default_factory=list)


class ListAnswer(AnswerBase):
    kind: Literal["list"] = "list"
    items: list[TextItem] = Field(default_factory=list)


class AmountAnswer(AnswerBase):
    kind: Literal["amount"] = "amount"
    items: list[AmountItem] = Field(default_factory=list)


class DateAnswer(AnswerBase):
    kind: Literal["date"] = "date"
    items: list[DateItem] = Field(default_factory=list)


class BooleanAnswer(AnswerBase):
    kind: Literal["boolean"] = "boolean"
    items: list[BooleanItem] = Field(default_factory=list)


class ConceptSearch(BaseModel):
    concept: str
    variants: list[str]
    pages_with_hits: list[str]
    line_hits: int


class Mention(BaseModel):
    doc_id: str
    line_num: int
    snippet: str
    why_not_an_answer: str


class ParseCoverage(BaseModel):
    model_config = ConfigDict(extra="allow")
    pages_total: int = 0
    pages_with_text: int = 0
    lines_total: int = 0
    sections_total: int = 0
    tables_total: int = 0
    cross_refs: int = 0
    fetched_at: str | None = None
    index_version: str | None = None
    pipeline_version: str | None = None


class AbsenceJustification(BaseModel):
    """"Not in this guide" with its four kinds of evidence: the concepts searched, the closest
    mentions and why they are not answers, the parse coverage, and a suggestion."""

    kind: Literal["absence"] = "absence"
    answer: None = None
    reason: AbsenceReason
    searched_concepts: list[ConceptSearch] = Field(default_factory=list)
    closest_mentions: list[Mention] = Field(default_factory=list)
    parse_coverage: ParseCoverage = Field(default_factory=ParseCoverage)
    suggestion: str | None = None
    suggested_clarification: str | None = None
    answer_found: bool = False
    complete_answer_found: bool = False


Answer = Annotated[Union[TextAnswer, ListAnswer, AmountAnswer, DateAnswer, BooleanAnswer], Field(discriminator="kind")]
AnswerOrAbsence = Annotated[
    Union[TextAnswer, ListAnswer, AmountAnswer, DateAnswer, BooleanAnswer, AbsenceJustification],
    Field(discriminator="kind"),
]
ANSWER_CLASSES: dict[str, type[AnswerBase]] = {
    "text": TextAnswer, "list": ListAnswer, "amount": AmountAnswer, "date": DateAnswer, "boolean": BooleanAnswer,
}


def expected_kind(answer_shape: str | None, answer_type: str | None) -> str:
    """The answer class a question calls for: listing wins, then the typed kinds, then text."""
    if answer_shape == "listing":
        return "list"
    t = answer_type or "text"
    if t in ("amount", "duration"):
        return "amount"
    if t in ("date", "boolean"):
        return t
    return "text"


class ValidationProblem(BaseModel):
    code: str
    message: str
    item_index: int | None = None
    span_index: int | None = None


class ActivationOut(BaseModel):
    on: bool
    reason: str


class GenerationMeta(BaseModel):
    """The `_meta` block of SPEC §4."""

    model_config = ConfigDict(extra="allow")
    question_id: str
    index_version: str | None = None
    pipeline_version: str
    methods_used: list[str] = Field(default_factory=list)
    methods_skipped: dict[str, str] = Field(default_factory=dict)
    activations: dict[str, ActivationOut] = Field(default_factory=dict)
    chunk_strategy: str = ""
    model_used: str = "no model"
    prompt_version: str | None = None
    fragments_applied: list[str] = Field(default_factory=list)
    iterations: int = 1
    validator_report: dict[str, list[ValidationProblem]] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    replay: dict[str, Any] | None = None


class Trace(BaseModel):
    """What replay needs: the parsed question and the plan as they were, plus the retrieval."""

    parsed: dict[str, Any]
    plan: dict[str, Any]
    retrieval: RetrievalResult


class GenerationResult(BaseModel):
    answer: AnswerOrAbsence
    meta: GenerationMeta
    trace: Trace | None = None

    def stable_json(self) -> str:
        """The JSON of the result without the timings: identical across runs of the same question."""
        return self.model_dump_json(exclude={"meta": {"timings_ms", "replay"}}, indent=None)
