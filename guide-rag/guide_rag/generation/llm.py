"""The optional model path of SPEC §4: an OpenAI-compatible endpoint, temperature 0, JSON-schema
structured output. The model returns line numbers and typed values, never a passage: every quote
is rebuilt from line_df by ids. Never called in tests without a mocked transport.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..retrieval.contracts import as_tables, attr
from ..retrieval.detectors import line_records
from ..retrieval.result import RetrievalResult
from .schemas import (ANSWER_CLASSES, Amount, AmountItem, AnswerBase, BooleanItem, DateItem, DateValue, Span,
                      TextItem, expected_kind)
from .verbatim import context_blocks

PROMPT_VERSION = "guide-rag/gen/1"
ENV_BASE_URL, ENV_KEY, ENV_MODEL = "GUIDE_RAG_LLM_BASE_URL", "GUIDE_RAG_LLM_KEY", "GUIDE_RAG_LLM_MODEL"
MAX_CONTEXT_CANDIDATES = 6


class NotConfigured(RuntimeError):
    """Raised when no key is configured; the pipeline then stays on the no-model path."""


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        key = os.environ.get(ENV_KEY, "").strip()
        if not key:
            raise NotConfigured(f"{ENV_KEY} is not set")
        return cls(
            base_url=os.environ.get(ENV_BASE_URL, "https://api.openai.com/v1").rstrip("/"),
            api_key=key,
            model=os.environ.get(ENV_MODEL, "gpt-4o-mini"),
        )


BASE_PROMPT = (
    "You answer a newcomer's question about Luxembourg from numbered lines of a public guide. "
    "The lines are the only source. Return JSON only, matching the schema. "
    "Cite by doc_id and line numbers (line_start, line_end) that appear in the context; never copy a passage, "
    "the quotes are rebuilt from the lines by their numbers. "
    "Set answer_found true only when the lines answer the question; set complete_answer_found true only when "
    "nothing is missing. List in discovered_keywords the words of the lines a reader would have used for this "
    "question but which are absent from the question. Do not invent anything outside the lines."
)
SHAPE_FRAGMENTS: dict[str, str] = {
    "text": "Shape text: one item, text = a short answer in the words of the lines, with one span (doc_id, line_start, line_end).",
    "list": "Shape list: one item per element of the list the question asks for, each with its own one-line span.",
    "amount": "Shape amount: value as a number, currency (EUR or null), unit (null or e.g. 'mois de loyer'); span = the line that carries the number.",
    "date": "Shape date: iso as YYYY-MM-DD and original as written in the line; span = the line that carries the date.",
    "boolean": "Shape boolean: boolean true or false as the lines state it; span = the line that states it.",
}
CONSTRAINTS_FRAGMENT = (
    "Constraints: temperature 0; only line numbers present in the context; an item without a span is invalid; "
    "when the lines do not answer, return no item and answer_found false."
)


def response_schema(kind: str) -> dict:
    """The JSON schema the model must fill; one item shape per answer kind."""
    span = {"type": "object", "properties": {"doc_id": {"type": "string"}, "line_start": {"type": "integer"},
                                              "line_end": {"type": "integer"}}, "required": ["doc_id", "line_start", "line_end"],
            "additionalProperties": False}
    value_props: dict[str, dict] = {
        "text": {"text": {"type": "string"}},
        "list": {"text": {"type": "string"}},
        "amount": {"value": {"type": "number"}, "currency": {"type": ["string", "null"]}, "unit": {"type": ["string", "null"]}},
        "date": {"iso": {"type": "string"}, "original": {"type": "string"}},
        "boolean": {"boolean": {"type": "boolean"}},
    }[kind]
    item = {"type": "object", "properties": {**value_props, "spans": {"type": "array", "items": span}},
            "required": list(value_props) + ["spans"], "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "answer_found": {"type": "boolean"},
            "complete_answer_found": {"type": "boolean"},
            "items": {"type": "array", "items": item},
            "discovered_keywords": {"type": "array", "items": {"type": "string"}},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer_found", "complete_answer_found", "items", "discovered_keywords", "caveats"],
        "additionalProperties": False,
    }


@dataclass
class LLMInfo:
    model_used: str
    prompt_version: str
    fragments_applied: list[str]
    raw: dict = field(default_factory=dict)


class LLMClient:
    """A thin OpenAI-compatible chat client; `transport` lets tests mock the network."""

    def __init__(self, config: LLMConfig | None = None, transport: httpx.BaseTransport | None = None, timeout: float = 60.0):
        self.config = config or LLMConfig.from_env()
        self._client = httpx.Client(base_url=self.config.base_url, transport=transport, timeout=timeout,
                                    headers={"Authorization": f"Bearer {self.config.api_key}"})

    def complete(self, system: str, user: str, schema: dict, schema_name: str = "guide_rag_answer") -> dict:
        body = {
            "model": self.config.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
        }
        r = self._client.post("/chat/completions", json=body)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content


def build_prompt(parsed: Any, retrieval: RetrievalResult, tables: Any, kind: str) -> tuple[str, str, list[str]]:
    """(system, user, fragments_applied). The context is numbered lines of the kept candidates."""
    fragments = ["base", f"shape:{kind}", "constraints"]
    system = "\n\n".join([BASE_PROMPT, SHAPE_FRAGMENTS[kind], CONSTRAINTS_FRAGMENT])
    t = as_tables(tables)
    shown = [c for c in retrieval.candidates if c.role in ("primary", "supporting")][:MAX_CONTEXT_CANDIDATES]
    lines = line_records(t.line_df, {c.context.doc_id for c in shown})
    blocks: list[str] = []
    for c in shown:
        rows = [l for l in lines if l.doc_id == c.context.doc_id and c.context.line_start <= l.line_num <= c.context.line_end]
        header = f"[{c.candidate_id}] {c.breadcrumb or c.section_title} ({c.role})"
        blocks.append(header + "\n" + "\n".join(f"{l.doc_id} L{l.line_num}: {l.text}" for l in rows))
    user = f"Question: {attr(parsed, 'corrected_question') or attr(parsed, 'original_question')}\n\nContext:\n" + "\n\n".join(blocks)
    return system, user, fragments


def generate_with_llm(parsed: Any, retrieval: RetrievalResult, tables: Any, client: LLMClient) -> tuple[AnswerBase, LLMInfo]:
    kind = expected_kind(attr(parsed, "answer_shape"), attr(parsed, "answer_type"))
    system, user, fragments = build_prompt(parsed, retrieval, tables, kind)
    raw = client.complete(system, user, response_schema(kind))
    info = LLMInfo(model_used=client.config.model, prompt_version=PROMPT_VERSION, fragments_applied=fragments, raw=raw)

    t = as_tables(tables)
    lines = {(l.doc_id, l.line_num): l.text for l in line_records(t.line_df)}

    def spans_of(item: dict) -> list[Span]:
        out = []
        for s in item.get("spans", []):
            doc_id, a, b = str(s["doc_id"]), int(s["line_start"]), int(s["line_end"])
            texts = [lines[(doc_id, n)] for n in range(a, b + 1) if (doc_id, n) in lines]
            # The quote is the lines themselves (rule 3); a span outside line_df has no quote and fails validation.
            out.append(Span(doc_id=doc_id, line_start=a, line_end=b, quote=" ".join(texts) if texts and len(texts) == b - a + 1 else None))
        return out

    items: list = []
    for it in raw.get("items", []):
        spans = spans_of(it)
        if kind == "amount":
            items.append(AmountItem(amount=Amount(value=float(it["value"]), currency=it.get("currency"), unit=it.get("unit")), spans=spans))
        elif kind == "date":
            items.append(DateItem(date=DateValue(iso=str(it["iso"]), original=str(it.get("original", it["iso"]))), spans=spans))
        elif kind == "boolean":
            items.append(BooleanItem(boolean=bool(it["boolean"]), spans=spans))
        else:
            # The displayed text is the cited lines, not the model's words: rule 3.
            text = " ".join(s.quote for s in spans if s.quote) or str(it.get("text", ""))
            items.append(TextItem(text=text, spans=spans))
    extraction = {"amount": "computed", "date": "computed", "boolean": "inferred"}.get(kind, "verbatim")
    answer = ANSWER_CLASSES[kind](
        items=items,
        extraction_method=extraction if items else "na",
        confidence=retrieval.confidence,
        caveats=[str(c) for c in raw.get("caveats", [])],
        answer_found=bool(raw.get("answer_found")) and bool(items),
        complete_answer_found=bool(raw.get("complete_answer_found")) and bool(items),
        context_structured=context_blocks(retrieval.primaries),
        keywords_found=sorted({k for c in retrieval.primaries for k in c.matched_keywords}),
        llm_discovered_keywords=sorted({str(k) for k in raw.get("discovered_keywords", [])}),
    )
    return answer, info
