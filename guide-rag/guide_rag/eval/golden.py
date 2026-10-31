"""The golden set: `eval/golden.yaml`, one question per row with what the guide should answer."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

QuestionType = Literal[
    "factual", "listing", "amount", "date", "yes/no", "address/phone", "typo", "EN", "DE", "on-page", "compound", "vague", "out-of-scope",
]
GOLDEN_PATH = Path("eval") / "golden.yaml"


class Expected(BaseModel):
    """Where the answer lives: the page, one or more sections (ids or titles), optionally a line range."""

    doc_id: str
    sections: list[str] = Field(default_factory=list)
    lines: list[int] | None = None  # [first, last], inclusive


class GoldenQuestion(BaseModel):
    id: str
    type: QuestionType
    question: str
    page: str | None = None  # the page the reader is on (pages_hint)
    expected: Expected | Literal["absent", "clarify"]
    note: str | None = None

    @property
    def expects_absence(self) -> bool:
        return self.expected == "absent"

    @property
    def expects_clarification(self) -> bool:
        return self.expected == "clarify"


def load_golden(path: Path | str = GOLDEN_PATH) -> list[GoldenQuestion]:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    questions = [GoldenQuestion.model_validate(row) for row in raw.get("questions", [])]
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("golden.yaml repeats a question id")
    return questions
