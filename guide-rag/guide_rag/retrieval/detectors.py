"""The deterministic detectors of SPEC §3. They always run; nothing here calls a model.

Each detector returns `Hit` rows keyed by (doc_id, line_num) so the aggregation to sections, the
co-occurrence boost and the audit all read the same shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .contracts import Term
from .text import fold, phrase_in, stems

CURRENT_PAGE_FACTOR = 1.3
CO_OCCURRENCE_LINE_FACTOR = 1.5
CO_OCCURRENCE_SECTION_FACTOR = 1.2

# The anchor kinds, and which answer_type requires which ("two-signal match").
ANCHOR_KIND_BY_ANSWER_TYPE: dict[str, str | None] = {
    "amount": "amount",
    "date": "date",
    "phone": "phone",
    "address": "postal_code",
    "url": "url",
    "duration": "duration",
    "text": None,
    "boolean": None,
}


@dataclass(frozen=True)
class Hit:
    doc_id: str
    line_num: int
    section_id: str | None
    method: str  # keyword_lines | title_match | anchor_regex | row_match
    keyword: str
    concept_key: str
    weight: float
    capture: dict | None = None


@dataclass
class LineRecord:
    doc_id: str
    line_num: int
    text: str
    element: str
    section_id: str | None
    anchor_id: str | None
    is_heading: bool
    stems: list[str] = field(default_factory=list)


def _s(value: Any) -> str:
    """A missing pandas cell (None/NaN) reads as the empty string."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def line_records(line_df: Any, doc_ids: Iterable[str] | None = None) -> list[LineRecord]:
    """line_df rows as records with their stems computed once; restricted to `doc_ids` when given."""
    if line_df is None or len(line_df) == 0:
        return []
    df = line_df
    if doc_ids is not None:
        wanted = set(doc_ids)
        df = df[df["doc_id"].isin(wanted)]
    cols = set(df.columns)
    out: list[LineRecord] = []
    for row in df.sort_values(["doc_id", "line_num"]).to_dict("records"):
        text = _s(row.get("text"))
        element = _s(row.get("element")) if "element" in cols else ""
        is_heading = bool(row.get("is_heading")) if "is_heading" in cols else element.startswith("h")
        out.append(
            LineRecord(
                doc_id=str(row["doc_id"]),
                line_num=int(row["line_num"]),
                text=text,
                element=element,
                section_id=_s(row.get("section_id")) or None,
                anchor_id=_s(row.get("anchor_id")) or None,
                is_heading=is_heading,
                stems=stems(text),
            )
        )
    return out


# --- keyword_lines ----------------------------------------------------------------------------


def keyword_lines(lines: list[LineRecord], terms: list[Term]) -> list[Hit]:
    """Every line containing a keyword: whole words, accent-folded, stem-equal; regex terms search raw text."""
    hits: list[Hit] = []
    compiled: list[tuple[Term, list[str] | None, re.Pattern[str] | None]] = []
    for t in terms:
        if t.is_regex:
            try:
                compiled.append((t, None, re.compile(t.text, re.IGNORECASE)))
            except re.error:
                continue  # a broken pattern from upstream must not stop the deterministic path
        else:
            ps = stems(t.text)
            if ps:
                compiled.append((t, ps, None))
    for line in lines:
        for t, ps, rx in compiled:
            matched = phrase_in(ps, line.stems) if ps is not None else bool(rx.search(line.text))
            if matched:
                hits.append(
                    Hit(line.doc_id, line.line_num, line.section_id, "keyword_lines", t.text, t.concept_key, t.weight)
                )
    return hits


# --- title_match ------------------------------------------------------------------------------


@dataclass(frozen=True)
class TitleHit:
    doc_id: str
    section_id: str
    title: str
    keyword: str
    concept_key: str
    weight: float


def title_match(toc_df: Any, terms: list[Term], doc_ids: Iterable[str] | None = None) -> list[TitleHit]:
    """Keywords against toc_df.title; a title hit is a strong anchor for the whole section."""
    if toc_df is None or len(toc_df) == 0:
        return []
    df = toc_df
    if doc_ids is not None:
        df = df[df["doc_id"].isin(set(doc_ids))]
    hits: list[TitleHit] = []
    phrase_terms = [(t, stems(t.text)) for t in terms if not t.is_regex and stems(t.text)]
    for row in df.sort_values(["doc_id", "start_line"]).to_dict("records"):
        title = _s(row.get("title"))
        title_stems = stems(title)
        for t, ps in phrase_terms:
            if phrase_in(ps, title_stems):
                hits.append(TitleHit(str(row["doc_id"]), str(row["section_id"]), title, t.text, t.concept_key, t.weight))
    return hits


# --- anchor_regex -----------------------------------------------------------------------------

_FR_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_DE_MONTHS = {
    "januar": 1, "februar": 2, "marz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
_MONTHS = {**_FR_MONTHS, **_EN_MONTHS, **_DE_MONTHS}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NUMBER_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "zwolf": 12, "zwanzig": 20, "dreissig": 30,
}
_NUM_WORD_ONE = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
# Compound number words: "vingt-six", "quatre-vingt-dix", "soixante et un", "twenty one".
_NUM_WORD_ALT = rf"(?:{_NUM_WORD_ONE})(?:[- ](?:et[- ])?(?:{_NUM_WORD_ONE}))*"


def number_word_value(text: str) -> float | None:
    """"vingt-six" -> 26, "quatre-vingt-dix" -> 90, "soixante et un" -> 61; None when a part is unknown."""
    parts = [p for p in re.split(r"[- ]", text.strip()) if p and p != "et"]
    total, run = 0.0, 0.0
    for p in parts:
        v = _NUMBER_WORDS.get(p)
        if v is None:
            return None
        if v == 20 and run == 4:  # quatre-vingt(s)
            run = 80
        elif v == 100 and run:
            run *= 100
        else:
            run += v
    total += run
    return total or None
_NUMBER = r"\d{1,3}(?:[ .]\d{3})*(?:[,.]\d+)?|\d+(?:[,.]\d+)?"

# Patterns run on the folded text (accents gone, lowercase), so "février" and "Fevrier" both match.
PATTERNS: dict[str, list[re.Pattern[str]]] = {
    # An amount is a sum of money or a count of time units ("vingt-six jours", "deux mois de loyer"):
    # "combien de jours" asks for an amount whose unit is a day.
    "amount": [
        re.compile(rf"(?P<value>{_NUMBER})\s*(?P<currency>€|eur\b|euros?\b)"),
        re.compile(rf"(?P<currency>€|eur)\s*(?P<value>{_NUMBER})"),
        re.compile(rf"(?<![\w-])(?P<words>{_NUM_WORD_ALT}|\d+)\s+(?P<unit>mois de loyer|months? of rent|monatsmieten?)\b"),
        re.compile(
            rf"(?<![\w-])(?P<words>{_NUM_WORD_ALT}|\d+)\s+(?P<unit>jours?(?: ouvrables)?|semaines?|mois|ans?|annees?|days?|weeks?|months?|years?|tage?n?|wochen?|monate?n?|jahren?)\b"
        ),
    ],
    "date": [
        re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
        re.compile(rf"\b(?P<d>\d{{1,2}})(?:er|st|nd|rd|th)?\.?\s+(?P<month>{_MONTH_ALT})\s+(?P<y>\d{{4}})\b"),
        re.compile(rf"\b(?P<month>{_MONTH_ALT})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b"),
        re.compile(r"\b(?P<d>\d{1,2})[/.](?P<m>\d{1,2})[/.](?P<y>\d{4})\b"),
    ],
    "phone": [
        re.compile(r"(?:\+352|00352)[\s.-]?\d(?:[\s.-]?\d){5,8}\b"),
        re.compile(r"\b6\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b"),
        re.compile(r"\b\d{2}[\s.-]\d{2}[\s.-]\d{2}[\s.-]\d{2}\b"),
        re.compile(r"\b11[2-8]\b"),  # the short emergency numbers (112, 113)
    ],
    "postal_code": [re.compile(r"\bl-\s?\d{4}\b")],
    "url": [re.compile(r"\bhttps?://[^\s<>\"']+|\bwww\.[^\s<>\"']+")],
    "duration": [
        re.compile(
            rf"(?<![\w-])(?P<words>{_NUM_WORD_ALT}|\d+)\s+(?P<unit>jours?(?: ouvrables)?|semaines?|mois|ans?|annees?|days?|weeks?|months?|years?|tage?n?|wochen?|monate?n?|jahren?)\b"
        ),
    ],
}


def _number(text: str) -> float | None:
    t = text.strip().replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) != 3 else t.replace(",", "")
    elif t.count(".") == 1 and len(t.split(".")[-1]) == 3:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _capture(kind: str, m: re.Match[str], raw_text: str) -> dict | None:
    """The typed value of one match; None when the match is not a real value (bad date, no number)."""
    g = m.groupdict()
    base = {"kind": kind, "raw": m.group(0).strip(), "pos": m.start(), "end": m.end()}
    if kind == "amount":
        if g.get("words") is not None:
            w = g["words"]
            value = float(w) if w.isdigit() else number_word_value(w)
            if not value:
                return None
            return {**base, "value": value, "currency": None, "unit": g.get("unit")}
        value = _number(g["value"])
        if value is None:
            return None
        return {**base, "value": value, "currency": "EUR", "unit": None}
    if kind == "duration":
        w = g["words"]
        value = float(w) if w.isdigit() else number_word_value(w)
        if not value:
            return None
        return {**base, "value": value, "currency": None, "unit": g.get("unit")}
    if kind == "date":
        y = int(g["y"])
        month = g.get("month")
        mo = _MONTHS[month] if month else int(g["m"])
        d = int(g["d"])
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return {**base, "iso": f"{y:04d}-{mo:02d}-{d:02d}", "original": base["raw"]}
    return {**base, "value": base["raw"]}


def find_anchors(text: str, kind: str) -> list[dict]:
    """Every typed value of `kind` in one text, left to right, deduplicated by raw text."""
    folded = fold(text)
    out: list[dict] = []
    seen: set[str] = set()
    for rx in PATTERNS.get(kind, []):  # the more specific patterns come first: "deux mois de loyer" before "deux mois"
        for m in rx.finditer(folded):
            cap = _capture(kind, m, text)
            if cap is None or cap["raw"] in seen:
                continue
            if any(cap["pos"] < o["end"] and o["pos"] < cap["end"] for o in out):
                continue  # overlaps a capture already kept
            seen.add(cap["raw"])
            out.append(cap)
    out.sort(key=lambda c: c["pos"])  # reading order, whatever pattern found them
    for c in out:
        c.pop("end", None)
    return out


def anchor_regex(lines: list[LineRecord], kind: str) -> list[Hit]:
    """Amount/date/phone/postal-code/url hits with their typed capture; the line is the span."""
    hits: list[Hit] = []
    for line in lines:
        for cap in find_anchors(line.text, kind):
            hits.append(
                Hit(line.doc_id, line.line_num, line.section_id, "anchor_regex", cap["raw"], "anchor:" + kind, 1.0, cap)
            )
    return hits


# --- row_match --------------------------------------------------------------------------------


def row_match(row_df: Any, terms: list[Term], lines: list[LineRecord] | None = None,
              doc_ids: Iterable[str] | None = None) -> list[Hit]:
    """Keywords against row_df.row_serialized; the section comes from line_df by (doc_id, line_num)."""
    if row_df is None or len(row_df) == 0:
        return []
    df = row_df
    if doc_ids is not None:
        df = df[df["doc_id"].isin(set(doc_ids))]
    section_of: dict[tuple[str, int], str | None] = {(l.doc_id, l.line_num): l.section_id for l in (lines or [])}
    phrase_terms = [(t, stems(t.text)) for t in terms if not t.is_regex and stems(t.text)]
    hits: list[Hit] = []
    for row in df.sort_values(["doc_id", "line_num"]).to_dict("records"):
        serialized = _s(row.get("row_serialized"))
        row_stems = stems(serialized)
        doc_id, line_num = str(row["doc_id"]), int(row["line_num"])
        for t, ps in phrase_terms:
            if phrase_in(ps, row_stems):
                hits.append(Hit(doc_id, line_num, section_of.get((doc_id, line_num)), "row_match", t.text, t.concept_key, t.weight))
    return hits


# --- co-occurrence and the reader's page ------------------------------------------------------


def co_occurrence(hits: Iterable[Hit]) -> tuple[set[tuple[str, int]], set[tuple[str, str]]]:
    """Lines and sections where >= 2 distinct concepts hit; a typed anchor counts as a concept."""
    by_line: dict[tuple[str, int], set[str]] = {}
    by_section: dict[tuple[str, str], set[str]] = {}
    for h in hits:
        by_line.setdefault((h.doc_id, h.line_num), set()).add(h.concept_key)
        if h.section_id:
            by_section.setdefault((h.doc_id, h.section_id), set()).add(h.concept_key)
    lines = {k for k, v in by_line.items() if len(v) >= 2}
    sections = {k for k, v in by_section.items() if len(v) >= 2}
    return lines, sections


def current_page_boost(score: float, doc_id: str, pages_hint: Iterable[str] | None,
                       factor: float = CURRENT_PAGE_FACTOR) -> float:
    """x1.3 on the page the reader is on, nothing elsewhere."""
    if pages_hint and doc_id in set(pages_hint):
        return score * factor
    return score


def required_anchor_kind(answer_type: str | None) -> str | None:
    return ANCHOR_KIND_BY_ANSWER_TYPE.get(str(answer_type or "text"))
