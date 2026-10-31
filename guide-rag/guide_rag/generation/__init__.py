"""Brick 4: generation (SPEC §4). Typed answers, the validator, the absence justification, the meta block."""

from .absence import build_absence
from .meta import build_meta
from .pipeline import PIPELINE_VERSION, answer_question, replay
from .schemas import (AbsenceJustification, Amount, AmountAnswer, AmountItem, AnswerBase, BooleanAnswer, BooleanItem,
                      ConceptSearch, DateAnswer, DateItem, DateValue, GenerationMeta, GenerationResult, ListAnswer,
                      Mention, ParseCoverage, Span, TextAnswer, TextItem, ValidationProblem)
from .validator import validate
from .verbatim import generate_verbatim

__all__ = [
    "AbsenceJustification", "Amount", "AmountAnswer", "AmountItem", "AnswerBase", "BooleanAnswer", "BooleanItem",
    "ConceptSearch", "DateAnswer", "DateItem", "DateValue", "GenerationMeta", "GenerationResult", "ListAnswer",
    "Mention", "PIPELINE_VERSION", "ParseCoverage", "Span", "TextAnswer", "TextItem", "ValidationProblem",
    "answer_question", "build_absence", "build_meta", "generate_verbatim", "replay", "validate",
]
