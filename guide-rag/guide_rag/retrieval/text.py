"""Folding, tokens and whole-word matching shared by the detectors, the router and the sweep.

Everything here is pure and deterministic: the same text always folds to the same tokens, so a
keyword hit is reproducible and auditable. A JS port must mirror these rules exactly.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_WS = re.compile(r"\s+")
# A hyphenated compound is one token ("car-pass", "rendez-vous"): a bare "car" never matches inside it.
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", " ": " ", " ": " "})

# Generic verbs and nouns a reader types around the subject ("acheter", "documents"). They weigh 0.3
# as content words and can never anchor a primary alone (the series' coverage rule). The list is
# brick 2's asset dictionary/weak_words.yaml, matched by stem; retrieval reads it, never redefines it.
_WEAK: object | None = None


def _weak_words() -> object:
    """Brick 2's WeakWords (stem membership via `in`), or an empty set when the asset is absent."""
    global _WEAK
    if _WEAK is None:
        try:
            from guide_rag.question.normalize import WeakWords

            _WEAK = WeakWords.load()
        except Exception:  # the asset or brick 2 is missing: nothing is weak, nothing breaks
            _WEAK = frozenset()
    return _WEAK

# A procedure question ("comment …", "how do I …") is answered by a section's steps, not a line.
PROCEDURE_CUES: tuple[str, ...] = ("comment", "how do i", "how do we", "how to", "how can i", "wie kann ich", "wie melde", "wie beantrage")


def squash(text: object) -> str:
    """Whitespace normalisation only; used to compare quotes with cited lines."""
    if text is None or (isinstance(text, float) and text != text):
        return ""
    return _WS.sub(" ", str(text).translate(_APOSTROPHES)).strip()


@lru_cache(maxsize=65536)
def fold(text: str) -> str:
    """Lowercase, strip accents, squash whitespace. Used for matching only, never for display."""
    text = squash(text)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def tokens(text: str) -> list[str]:
    """Word tokens of the folded text; "l'état" gives ["l", "etat"], "car-pass" stays one token."""
    return _TOKEN.findall(fold(text))


# Derivational endings folded when at least MIN_STEM letters remain: "immatriculer" and
# "immatriculation" meet at "immatricul", "assurer" and "assurance" at "assur", "couvre" and
# "couvrant" at "couvr". Longest first; one ending at most.
_DERIVATIONS = ("ation", "ement", "ance", "ant", "er")
MIN_STEM = 5


@lru_cache(maxsize=65536)
def stem(token: str) -> str:
    """A light FR/EN stem: plurals, a final mute e and a few derivational endings fall, so
    "garanties" meets "garantie" and "immatriculer" meets "immatriculation".

    Hyphenated compounds are stemmed part by part ("rendez-vous" -> "rendez-vou").
    """
    if "-" in token:
        return "-".join(stem(p) for p in token.split("-"))
    if len(token) <= 3:
        return token
    if token.endswith("eaux"):
        return token[:-1]
    if token.endswith("aux") and len(token) > 4:
        return token[:-3] + "al"
    if token.endswith(("s", "x")) and not token.endswith("ss"):
        token = token[:-1]
    for ending in _DERIVATIONS:
        if token.endswith(ending) and len(token) - len(ending) >= MIN_STEM:
            return token[: -len(ending)]
    if len(token) > 5 and token.endswith("e"):
        token = token[:-1]
    return token


def stems(text: str) -> list[str]:
    return [stem(t) for t in tokens(text)]


def phrase_in(phrase_stems: list[str], line_stems: list[str]) -> bool:
    """True when the phrase appears as consecutive whole words (stem-equal) in the line.

    A multi-word phrase also matches one hyphenated line token whose parts are the phrase
    ("rendez vous" meets "rendez-vous"); a one-word phrase never matches inside a compound.
    """
    n = len(phrase_stems)
    if n == 0:
        return False
    if n <= len(line_stems):
        for i in range(len(line_stems) - n + 1):
            if line_stems[i : i + n] == phrase_stems:
                return True
    if n >= 2:
        joined = "-".join(phrase_stems)
        return any("-" in t and t == joined for t in line_stems)
    return False


def contains_keyword(text: str, keyword: str) -> bool:
    return phrase_in(stems(keyword), stems(text))


def variant_regex(variant: str) -> re.Pattern[str]:
    """A whole-word regex over folded text for one dictionary variant; plurals allowed.

    Word boundaries exclude hyphens, so "car" does not match "car-pass" here either.
    """
    parts = [re.escape(t) + r"(?:s|x|es)?" for t in tokens(variant)]
    if not parts:
        return re.compile(r"(?!x)x")  # never matches: an empty variant hits nothing
    return re.compile(r"(?<![\w-])" + r"[\s-]+".join(parts) + r"(?![\w-])")


def is_weak(text: str) -> bool:
    """A generic word (every token of it, by brick 2's stem list) that cannot carry a question's subject."""
    ts = tokens(text)
    if not ts:
        return True
    weak = _weak_words()
    return all(t in weak for t in ts)


def is_procedure_question(text: str) -> bool:
    folded = " " + fold(text) + " "
    return any(f" {cue} " in folded for cue in PROCEDURE_CUES)


def concept_label(concept: str) -> str:
    """"garantie_locative" reads as "garantie locative" in a reason sentence."""
    return concept.replace("_", " ")


def snippet_of(text: str, limit: int = 160) -> str:
    text = squash(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
