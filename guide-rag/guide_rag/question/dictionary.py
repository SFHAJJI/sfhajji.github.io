"""The expert dictionary: concepts, their keyword variants, and the matcher over question tokens.

The YAML files under `dictionary/` are the asset; this module only loads them into two frames
(`concepts_df`, `concept_keywords_df`) and matches variants against folded, stemmed tokens. A
model never writes here: entries grow by pull request, with a line in `dictionary/CHANGELOG.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

from guide_rag.question.normalize import DICTIONARY_DIR, content_tokens, fold, fold_tokens
from guide_rag.question.stopwords import stem

TOPICS: tuple[str, ...] = ("housing", "vehicle", "liability", "administration", "health", "work", "money", "other")
LANGUAGES: tuple[str, ...] = ("fr", "en", "de", "lb")
PRIORITIES: tuple[str, ...] = ("primary", "secondary")

# A variant with too short a match key would fire on noise: "a", "l", "1". Two is enough for "rc".
MIN_KEY_CHARS = 2
_LANGUAGE_ORDER = {"fr": 0, "en": 1, "de": 2, "lb": 3}


def match_key(keyword: str) -> tuple[str, ...]:
    """The stems of the folded content tokens of a variant: what the question is compared to."""
    return tuple(stem(t) for t in content_tokens(fold_tokens(keyword)))


@dataclass(frozen=True)
class Variant:
    concept: str
    topic: str
    language: str
    keyword: str
    priority: str
    weight: float
    key: tuple[str, ...]


@dataclass(frozen=True)
class ConceptMatch:
    """A variant found in the question: `start..end` are token positions (end exclusive)."""

    concept: str
    topic: str
    keyword: str
    language: str
    priority: str
    weight: float
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


class Dictionary:
    """Concepts and variants, loaded once, matched many times."""

    def __init__(self, concepts_df: pd.DataFrame, concept_keywords_df: pd.DataFrame):
        self.concepts_df = concepts_df.reset_index(drop=True)
        self.concept_keywords_df = concept_keywords_df.reset_index(drop=True)
        self._validate()
        self._topic: dict[str, str] = dict(zip(self.concepts_df["concept"], self.concepts_df["topic"]))
        self._definition: dict[str, str] = dict(zip(self.concepts_df["concept"], self.concepts_df["definition"]))
        self._variants: list[Variant] = []
        self._by_key: dict[tuple[str, ...], list[Variant]] = {}
        self._by_concept: dict[str, list[Variant]] = {}
        for row in self.concept_keywords_df.itertuples(index=False):
            key = match_key(str(row.keyword))
            if not key or sum(len(k) for k in key) < MIN_KEY_CHARS:
                raise ValueError(f"variant {row.keyword!r} of {row.concept} has no usable match key")
            variant = Variant(
                concept=str(row.concept),
                topic=self._topic[str(row.concept)],
                language=str(row.language),
                keyword=str(row.keyword),
                priority=str(row.priority),
                weight=float(row.weight),
                key=key,
            )
            self._variants.append(variant)
            self._by_key.setdefault(key, []).append(variant)
            self._by_concept.setdefault(variant.concept, []).append(variant)
        self._max_key_len = max((len(k) for k in self._by_key), default=1)

    # -- construction

    @classmethod
    def load(cls, path: Path | None = None) -> "Dictionary":
        """Read `concepts.yaml` and `keywords.yaml` from `dictionary/` (or another folder)."""
        folder = Path(path) if path else DICTIONARY_DIR
        with open(folder / "concepts.yaml", encoding="utf-8") as fh:
            concepts = (yaml.safe_load(fh) or {}).get("concepts", [])
        with open(folder / "keywords.yaml", encoding="utf-8") as fh:
            keywords = (yaml.safe_load(fh) or {}).get("keywords", [])
        concepts_df = pd.DataFrame(concepts, columns=["concept", "topic", "definition"])
        keywords_df = pd.DataFrame(keywords, columns=["concept", "language", "keyword", "priority", "weight"])
        keywords_df["keyword"] = keywords_df["keyword"].astype(str)
        return cls(concepts_df, keywords_df)

    def _validate(self) -> None:
        """Fail loudly at load time: a broken dictionary must not parse questions quietly."""
        concepts = self.concepts_df["concept"].tolist()
        if len(set(concepts)) != len(concepts):
            raise ValueError("concepts.yaml repeats a concept")
        bad_topics = sorted(set(self.concepts_df["topic"]) - set(TOPICS))
        if bad_topics:
            raise ValueError(f"concepts.yaml uses topics outside SPEC §1: {bad_topics}")
        unknown = sorted(set(self.concept_keywords_df["concept"]) - set(concepts))
        if unknown:
            raise ValueError(f"keywords.yaml names concepts absent from concepts.yaml: {unknown}")
        bad_lang = sorted(set(self.concept_keywords_df["language"]) - set(LANGUAGES))
        if bad_lang:
            raise ValueError(f"keywords.yaml uses unknown languages: {bad_lang}")
        bad_priority = sorted(set(self.concept_keywords_df["priority"]) - set(PRIORITIES))
        if bad_priority:
            raise ValueError(f"keywords.yaml uses unknown priorities: {bad_priority}")
        without_variant = sorted(set(concepts) - set(self.concept_keywords_df["concept"]))
        if without_variant:
            raise ValueError(f"concepts without any variant: {without_variant}")

    # -- lookups

    @property
    def concepts(self) -> list[str]:
        return self.concepts_df["concept"].tolist()

    def topic_of(self, concept: str) -> str:
        return self._topic[concept]

    def definition_of(self, concept: str) -> str:
        return self._definition[concept]

    def variants_of(self, concept: str) -> list[Variant]:
        return list(self._by_concept.get(concept, []))

    def terms(self) -> list[str]:
        """Every variant keyword, for the vocabulary: dictionary words are never typos."""
        return [v.keyword for v in self._variants]

    def tag_forms(self, concept: str) -> set[str]:
        """The folded strings a corpus tag may use for the concept: its id, with spaces, its variants."""
        forms = {fold(concept), fold(concept.replace("_", " "))}
        forms.update(fold(v.keyword) for v in self._by_concept.get(concept, []))
        return forms

    def label_of(self, concept: str, language: str) -> str:
        """The primary variant in the language, else in French, else the concept id."""
        variants = self._by_concept.get(concept, [])
        for lang in (language, "fr", "en"):
            for v in variants:
                if v.language == lang and v.priority == "primary":
                    return v.keyword
        return concept

    def concepts_for_token(self, token: str) -> list[tuple[str, str]]:
        """(concept, topic) pairs whose single-word variant matches a folded token; sorted."""
        key = (stem(fold(token)),)
        found = {(v.concept, v.topic) for v in self._by_key.get(key, [])}
        return sorted(found)

    # -- matching

    def match_concepts(self, tokens: Iterable[str]) -> list[ConceptMatch]:
        """Every variant found as a contiguous run of the question's content tokens.

        `tokens` are folded content tokens, in order. A longer variant covering a shorter one at
        the same place wins ("assurance auto" hides the bare "assurance" of three concepts), so a
        precise phrase is never ambiguous. Order: position, then longest, then concept name.
        """
        stems = [stem(t) for t in tokens]
        found: list[ConceptMatch] = []
        for start in range(len(stems)):
            for length in range(1, min(self._max_key_len, len(stems) - start) + 1):
                key = tuple(stems[start : start + length])
                for v in self._by_key.get(key, []):
                    found.append(
                        ConceptMatch(v.concept, v.topic, v.keyword, v.language, v.priority, v.weight, start, start + length)
                    )
        kept = [
            m
            for m in found
            if not any(o.length > m.length and o.start <= m.start and m.end <= o.end for o in found)
        ]
        # One match per concept and place: "commune" is a French and an English variant of the
        # same concept, and the concept must vote once. The primary, heaviest variant represents it.
        best: dict[tuple[str, int, int], ConceptMatch] = {}
        for m in kept:
            slot = (m.concept, m.start, m.end)
            rank = (m.priority != "primary", -m.weight, _LANGUAGE_ORDER.get(m.language, 9), m.keyword)
            current = best.get(slot)
            if current is None or rank < (
                current.priority != "primary", -current.weight, _LANGUAGE_ORDER.get(current.language, 9), current.keyword
            ):
                best[slot] = m
        return sorted(best.values(), key=lambda m: (m.start, -m.length, m.concept))

    def expand(self, concepts: Iterable[str | ConceptMatch]) -> list[Variant]:
        """Every variant, in every language, of the given concepts; first concept first."""
        seen: list[str] = []
        for item in concepts:
            concept = item.concept if isinstance(item, ConceptMatch) else item
            if concept not in seen:
                seen.append(concept)
        out: list[Variant] = []
        for concept in seen:
            out.extend(self._by_concept.get(concept, []))
        return out

    # -- reporting

    def size(self) -> dict[str, int]:
        counts = self.concept_keywords_df["language"].value_counts().to_dict()
        return {"concepts": len(self.concepts_df), "variants": len(self.concept_keywords_df), **{f"variants_{k}": int(v) for k, v in sorted(counts.items())}}
