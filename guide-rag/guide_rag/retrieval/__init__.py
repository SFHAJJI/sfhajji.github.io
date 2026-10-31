"""Brick 3: retrieval (SPEC §2b and §3). Deterministic filtering over the brick-1 tables."""

from .contracts import (Activation, Decomposition, ExecutionPlan, Keyword, ParsedQuestion, StructuralHints,
                        Tables)
from .result import CandidateScope, RetrievalResult, RetrievedCandidate, retrieve
from .sweep import SweepResult, SweepRow, sweep

__all__ = [
    "Activation", "CandidateScope", "Decomposition", "ExecutionPlan", "Keyword", "ParsedQuestion",
    "RetrievalResult", "RetrievedCandidate", "StructuralHints", "SweepResult", "SweepRow", "Tables",
    "retrieve", "sweep",
]
