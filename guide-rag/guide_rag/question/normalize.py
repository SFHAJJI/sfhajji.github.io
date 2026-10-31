"""Question normalisation: folding, tokens, abbreviations, spell correction, language.

Everything here is deterministic and model-free. The original wording is never lost: folding is
for matching only, and `corrected_question` is rebuilt from the lowercase original by replacing
tokens in place, so punctuation and word order survive.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from guide_rag.question.stopwords import (
    DE_STOP_WORDS,
    EN_STOP_WORDS,
    FR_STOP_WORDS,
    PRONOUN_PHRASES,
    PRONOUNS,
    EMPTY_CONTENT_WORDS,
    is_stop_word,
    stem,
)

DICTIONARY_DIR = Path(__file__).resolve().parents[2] / "dictionary"

# A word is letters and digits; apostrophes and hyphens split ("l'assurance" -> "l", "assurance").
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_FOLD_MAP = str.maketrans({"œ": "oe", "æ": "ae", "ß": "ss", "Œ": "oe", "Æ": "ae"})


def fold(text: str) -> str:
    """Lowercase and strip accents; ligatures are spelled out. For matching only."""
    text = text.lower().translate(_FOLD_MAP)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with their accents; apostrophes, hyphens and punctuation split."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text.replace("’", "'"))]


def fold_tokens(text: str) -> list[str]:
    return [fold(t) for t in tokenize(text)]


def content_tokens(folded_tokens: Iterable[str]) -> list[str]:
    """The tokens that can carry the subject: not a stop word, not a pronoun, not "chose"."""
    # Digits of any length stay: "112", "classe 1" and "L-1234" are subjects too.
    return [
        t
        for t in folded_tokens
        if not is_stop_word(t) and t not in PRONOUNS and t not in EMPTY_CONTENT_WORDS and (len(t) > 1 or t.isdigit())
    ]


# ----------------------------------------------------------------------------- abbreviations


@dataclass(frozen=True)
class Abbreviation:
    abbreviation: str
    expansion: str
    language: str | None = None
    note: str | None = None


class Abbreviations:
    """The table of `dictionary/abbreviations.yaml`, keyed by the folded short form."""

    def __init__(self, entries: Iterable[Abbreviation]):
        self._by_key: dict[str, Abbreviation] = {}
        for entry in entries:
            self._by_key[fold(entry.abbreviation)] = entry

    @classmethod
    def load(cls, path: Path | None = None) -> "Abbreviations":
        path = path or DICTIONARY_DIR / "abbreviations.yaml"
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        entries = [
            Abbreviation(
                abbreviation=str(row["abbreviation"]),
                expansion=str(row["expansion"]),
                language=row.get("language"),
                note=row.get("note"),
            )
            for row in raw.get("abbreviations", [])
        ]
        return cls(entries)

    def __len__(self) -> int:
        return len(self._by_key)

    def __contains__(self, token: str) -> bool:
        return fold(token) in self._by_key

    def get(self, token: str) -> Abbreviation | None:
        return self._by_key.get(fold(token))

    def items(self) -> Iterator[tuple[str, Abbreviation]]:
        return iter(sorted(self._by_key.items()))


# ----------------------------------------------------------------------------- weak words


class WeakWords:
    """The words of `dictionary/weak_words.yaml`: kept as keywords, never trusted to pick a topic.

    Matched by stem so "documents" and "document" are one entry; the same file is meant to be
    read by retrieval, so the rule is written once here and nowhere else.
    """

    def __init__(self, words_by_language: dict[str, Iterable[str]]):
        self._stems: dict[str, set[str]] = {lang: {stem(fold(w)) for w in words} for lang, words in words_by_language.items()}
        self._all: set[str] = set().union(*self._stems.values()) if self._stems else set()

    @classmethod
    def load(cls, path: Path | None = None) -> "WeakWords":
        path = path or DICTIONARY_DIR / "weak_words.yaml"
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls({lang: list(words or []) for lang, words in (raw.get("weak_words") or {}).items()})

    def __len__(self) -> int:
        return len(self._all)

    def __contains__(self, token: str) -> bool:
        return stem(fold(token)) in self._all

    def languages(self) -> list[str]:
        return sorted(self._stems)


# ----------------------------------------------------------------------------- vocabulary


def damerau_levenshtein(a: str, b: str, max_distance: int = 2) -> int:
    """Optimal string alignment distance with an early exit above `max_distance`.

    Tokens are short, so a plain dynamic programme is fast enough; the early exit keeps lookup
    cheap when the candidate set is large.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    previous2: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            if previous2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                current[j] = min(current[j], previous2[j - 2] + 1)
        if min(current) > max_distance:
            return max_distance + 1
        previous2, previous = previous, current
    return previous[len(b)]


@dataclass(frozen=True)
class Correction:
    original: str  # the folded token the reader typed
    corrected: str  # the folded corpus term
    display: str  # the corpus term as the corpus spells it (accents kept)
    distance: int
    frequency: int


class Vocabulary:
    """The corpus vocabulary with a SymSpell-like deletes index for spell correction.

    Built from `line_df.text` at runtime, never from a model. A token the corpus knows is never
    corrected; a token nothing is close to is kept as typed. Ties are broken by frequency, then by
    the alphabet, so the same typo always gets the same correction.
    """

    def __init__(
        self,
        counts: dict[str, int],
        display: dict[str, str] | None = None,
        *,
        known_terms: Iterable[str] = (),
        max_edit_distance: int = 2,
        prefix_length: int = 7,
        min_term_length: int = 3,
    ):
        self.max_edit_distance = max_edit_distance
        self.prefix_length = prefix_length
        self.min_term_length = min_term_length
        self._counts: dict[str, int] = {t: c for t, c in counts.items() if len(t) >= 1}
        self._display: dict[str, str] = dict(display or {})
        # Words the dictionary knows are never typos, even when the corpus does not use them.
        for term in known_terms:
            for token in tokenize(term):
                folded = fold(token)
                self._counts.setdefault(folded, 0)
                self._display.setdefault(folded, token)
        self._deletes: dict[str, list[str]] = {}
        for term in sorted(self._counts):
            if len(term) < min_term_length:
                continue
            for deleted in self._deletes_of(term[:prefix_length]):
                self._deletes.setdefault(deleted, []).append(term)

    # -- construction

    @classmethod
    def from_texts(cls, texts: Iterable[str], **kwargs) -> "Vocabulary":
        counts: Counter[str] = Counter()
        surface: dict[str, Counter[str]] = {}
        for text in texts:
            if not isinstance(text, str):
                continue
            for token in tokenize(text):
                folded = fold(token)
                counts[folded] += 1
                surface.setdefault(folded, Counter())[token] += 1
        display = {f: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for f, c in surface.items()}
        return cls(dict(counts), display, **kwargs)

    @classmethod
    def from_line_df(cls, line_df, text_column: str = "text", **kwargs) -> "Vocabulary":
        """The vocabulary of the citation units; an empty frame gives an empty vocabulary."""
        if line_df is None or len(line_df) == 0 or text_column not in line_df.columns:
            return cls({}, {}, **kwargs)
        return cls.from_texts(line_df[text_column].tolist(), **kwargs)

    # -- queries

    def __len__(self) -> int:
        return len(self._counts)

    def __contains__(self, token: str) -> bool:
        return fold(token) in self._counts

    def frequency(self, token: str) -> int:
        return self._counts.get(fold(token), 0)

    def display(self, folded_term: str) -> str:
        return self._display.get(folded_term, folded_term)

    def lookup(self, token: str) -> Correction | None:
        """The closest corpus term within the edit distance, or None to keep the token.

        Rules, in order: a known token is never corrected; tokens shorter than five letters or
        with digits are never corrected (codes, amounts, and short words a small corpus may lack:
        "page" must not become "paie"); tokens of six letters or fewer tolerate one edit only; a
        correction never lands on a stop word ("voiture" must not become "votre"), only on a term
        the corpus uses at least once, and keeps the first letter.
        """
        folded = fold(token)
        if folded in self._counts:
            return None
        if len(folded) < 5 or any(ch.isdigit() for ch in folded):
            return None
        allowed = 1 if len(folded) <= 6 else self.max_edit_distance
        candidates: set[str] = set()
        for deleted in self._deletes_of(folded[: self.prefix_length]):
            for term in self._deletes.get(deleted, ()):
                candidates.add(term)
        best: tuple[int, int, str] | None = None
        for term in candidates:
            if len(term) < 4 or is_stop_word(term) or self._counts[term] < 1 or term[0] != folded[0]:
                continue
            distance = damerau_levenshtein(folded, term, allowed)
            if distance > allowed:
                continue
            key = (distance, -self._counts[term], term)
            if best is None or key < best:
                best = key
        if best is None:
            return None
        distance, neg_freq, term = best
        return Correction(folded, term, self.display(term), distance, -neg_freq)

    def correct(self, token: str) -> str:
        found = self.lookup(token)
        return found.display if found else token

    # -- internals

    def _deletes_of(self, term: str) -> set[str]:
        """All strings within `max_edit_distance` deletions of `term`, the term included."""
        results = {term}
        frontier = {term}
        for _ in range(self.max_edit_distance):
            next_frontier: set[str] = set()
            for word in frontier:
                if len(word) <= 1:
                    continue
                for i in range(len(word)):
                    shorter = word[:i] + word[i + 1 :]
                    if shorter not in results:
                        results.add(shorter)
                        next_frontier.add(shorter)
            frontier = next_frontier
        return results


# ----------------------------------------------------------------------------- language


def detect_language(folded_tokens: Iterable[str], extra_votes: dict[str, int] | None = None) -> str:
    """Stop-word vote; `extra_votes` (e.g. the languages of matched dictionary variants) break ties.

    Returns "unknown" when nothing votes, so downstream never guesses silently.
    """
    votes = {"fr": 0, "en": 0, "de": 0}
    for token in folded_tokens:
        if token in FR_STOP_WORDS:
            votes["fr"] += 1
        if token in EN_STOP_WORDS:
            votes["en"] += 1
        if token in DE_STOP_WORDS:
            votes["de"] += 1
    best = _winner(votes)
    if best is not None:
        return best
    if extra_votes:
        merged = {lang: votes.get(lang, 0) + extra_votes.get(lang, 0) for lang in votes}
        best = _winner(merged)
        if best is not None:
            return best
    return "unknown"


def _winner(votes: dict[str, int]) -> str | None:
    top = max(votes.values())
    if top == 0:
        return None
    leaders = [lang for lang, v in votes.items() if v == top]
    if len(leaders) == 1:
        return leaders[0]
    # A tie between languages: accents decide for French, else the first in fr/en/de order would
    # be a guess, so say unknown.
    return None


# ----------------------------------------------------------------------------- the pipeline


@dataclass
class NormalizedQuestion:
    original: str
    corrected: str  # lowercase, abbreviations expanded, typos corrected, accents kept
    tokens: list[str]  # tokens of `corrected`, accents kept
    folded_tokens: list[str]  # the same, accent-folded
    content: list[str]  # folded content tokens (no stop words, no pronouns)
    expansions: list[tuple[str, str]] = field(default_factory=list)  # (abbreviation, expansion)
    corrections: list[Correction] = field(default_factory=list)
    language: str = "unknown"
    pronouns_seen: list[str] = field(default_factory=list)

    @property
    def folded(self) -> str:
        return fold(self.corrected)

    def stems(self) -> list[str]:
        return [stem(t) for t in self.content]


def normalize_question(
    question: str,
    *,
    vocabulary: Vocabulary | None = None,
    abbreviations: Abbreviations | None = None,
) -> NormalizedQuestion:
    """Lowercase, expand abbreviations, correct typos against the corpus, tokenise, vote a language.

    The abbreviation pass runs before the spell pass, so "RC" is never "corrected" to a corpus
    word. Both replace whole tokens inside the lowercase original: punctuation stays.
    """
    abbreviations = abbreviations or Abbreviations.load()
    lowered = question.strip().lower().replace("’", "'")
    expansions: list[tuple[str, str]] = []
    corrections: list[Correction] = []

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        abbreviation = abbreviations.get(token)
        if abbreviation is not None:
            expansions.append((token, abbreviation.expansion))
            return abbreviation.expansion
        folded = fold(token)
        if vocabulary is not None and not is_stop_word(folded) and folded not in PRONOUNS and folded not in EMPTY_CONTENT_WORDS:
            found = vocabulary.lookup(token)
            if found is not None:
                corrections.append(found)
                return found.display
        return token

    corrected = _WORD_RE.sub(replace, lowered)
    tokens = tokenize(corrected)
    folded_tokens = [fold(t) for t in tokens]
    folded_text = fold(corrected)
    pronouns_seen = [p for p in PRONOUN_PHRASES if p in folded_text]
    pronouns_seen += [t for t in folded_tokens if t in PRONOUNS]
    content = content_tokens(folded_tokens)
    return NormalizedQuestion(
        original=question,
        corrected=corrected,
        tokens=tokens,
        folded_tokens=folded_tokens,
        content=content,
        expansions=expansions,
        corrections=corrections,
        language=detect_language(folded_tokens),
        pronouns_seen=pronouns_seen,
    )
