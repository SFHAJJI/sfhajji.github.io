"""Brick 6: the evaluation per question type (SPEC §6), never one aggregate."""

from .golden import GoldenQuestion, load_golden
from .run import run_eval, write_reports

__all__ = ["GoldenQuestion", "load_golden", "run_eval", "write_reports"]
