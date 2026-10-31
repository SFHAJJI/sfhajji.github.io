"""The exhaustive absence sweep (SPEC §3): every variant of every concept of the question, as a
whole-word regex over EVERY line of EVERY page. Not top-k: zero rows for a concept is evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import as_tables, concept_variants, question_terms
from .detectors import _s
from .text import fold, snippet_of, variant_regex


@dataclass(frozen=True)
class SweepRow:
    concept: str
    variant: str
    doc_id: str
    line_num: int
    snippet: str


@dataclass
class ConceptSweep:
    concept: str
    variants: list[str]
    pages_with_hits: list[str] = field(default_factory=list)
    line_hits: int = 0


@dataclass
class SweepResult:
    rows: list[SweepRow]
    concepts: list[ConceptSweep]
    pages_scanned: int
    lines_scanned: int

    def rows_for(self, concept: str) -> list[SweepRow]:
        return [r for r in self.rows if r.concept == concept]


def question_concept_variants(parsed: Any, dictionary: Any = None) -> dict[str, list[str]]:
    """concept -> variants to sweep: the question's concepts (all their dictionary variants) plus
    every direct keyword without a concept, as a concept of its own."""
    by_concept = concept_variants(dictionary, parsed)
    terms = question_terms(parsed, by_concept)
    out: dict[str, list[str]] = {}
    for t in terms:
        if t.is_regex:
            continue
        variants = list(by_concept.get(t.concept_key, [])) if t.concept else []
        if t.text not in variants:
            variants.append(t.text)
        bucket = out.setdefault(t.concept_key, [])
        for v in variants:
            if v not in bucket:
                bucket.append(v)
    return out


def sweep(parsed: Any, tables: Any, dictionary: Any = None) -> SweepResult:
    """Every page, every line, every variant. Rows ordered by concept, page, line, variant."""
    t = as_tables(tables)
    by_concept = question_concept_variants(parsed, dictionary)
    line_df = t.line_df
    records = [] if line_df is None or len(line_df) == 0 else line_df.sort_values(["doc_id", "line_num"]).to_dict("records")
    folded = [(str(r["doc_id"]), int(r["line_num"]), _s(r.get("text"))) for r in records]
    rows: list[SweepRow] = []
    concepts: list[ConceptSweep] = []
    for concept, variants in by_concept.items():
        patterns = [(v, variant_regex(v)) for v in variants]
        pages: set[str] = set()
        n = 0
        for doc_id, line_num, text in folded:
            ftext = fold(text)
            for v, rx in patterns:
                if rx.search(ftext):
                    rows.append(SweepRow(concept, v, doc_id, line_num, snippet_of(text)))
                    pages.add(doc_id)
                    n += 1
        concepts.append(ConceptSweep(concept, list(variants), sorted(pages), n))
    return SweepResult(rows, concepts, len({d for d, _, _ in folded}), len(folded))
