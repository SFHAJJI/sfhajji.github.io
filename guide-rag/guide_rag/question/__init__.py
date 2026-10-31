"""Brick 2 of guide-rag: question parsing, the expert dictionary, the dispatcher, the briefs."""

from guide_rag.question.briefs import GenerationBrief, RetrievalBrief, generation_brief, retrieval_brief
from guide_rag.question.dictionary import ConceptMatch, Dictionary, Variant
from guide_rag.question.dispatcher import Activation, ExecutionPlan, dispatch
from guide_rag.question.normalize import (
    Abbreviations,
    Correction,
    NormalizedQuestion,
    Vocabulary,
    detect_language,
    fold,
    normalize_question,
    tokenize,
)
from guide_rag.question.parse_question import (
    Decomposition,
    Keyword,
    ParsedQuestion,
    ScopeFilters,
    StructuralHints,
    parse_question,
    question_id_of,
)

__all__ = [
    "Abbreviations",
    "Activation",
    "ConceptMatch",
    "Correction",
    "Decomposition",
    "Dictionary",
    "ExecutionPlan",
    "GenerationBrief",
    "Keyword",
    "NormalizedQuestion",
    "ParsedQuestion",
    "RetrievalBrief",
    "ScopeFilters",
    "StructuralHints",
    "Variant",
    "Vocabulary",
    "detect_language",
    "dispatch",
    "fold",
    "generation_brief",
    "normalize_question",
    "parse_question",
    "question_id_of",
    "retrieval_brief",
    "tokenize",
]
