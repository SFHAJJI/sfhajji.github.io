"""The minimal input of bricks 3 and 4, mirroring SPEC §2 (ParsedQuestion, ExecutionPlan) and §1 (tables).

Brick 2 produces the same shapes; everything here is read duck-typed, so any object (or dict) with
these attributes is accepted. The pydantic models exist for tests, traces and replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .text import fold, is_weak, phrase_in, stem, stems, tokens

KeywordSource = Literal["direct", "expert_dictionary", "anchor"]
AnswerShape = Literal["single", "listing"]
AnswerType = Literal["text", "amount", "date", "boolean", "address", "phone", "url", "duration"]
AnswerContext = Literal["line", "paragraph", "section"]

WEAK_WEIGHT = 0.3  # a generic content word counts this much in the coverage of a question


class Keyword(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str
    weight: float = 1.0
    source: KeywordSource = "direct"
    concept: str | None = None
    is_regex: bool = False


class StructuralHints(BaseModel):
    model_config = ConfigDict(extra="allow")
    pages_hint: list[str] | None = None
    toc_section_hint: str | None = None
    answer_context: AnswerContext = "paragraph"


class Decomposition(BaseModel):
    model_config = ConfigDict(extra="allow")
    pattern: Literal["single", "independent"] = "single"
    sub_questions: list[str] = Field(default_factory=list)


class ParsedQuestion(BaseModel):
    """The fields of SPEC §2 that retrieval and generation read."""

    model_config = ConfigDict(extra="allow")
    question_id: str
    original_question: str
    corrected_question: str
    language: Literal["fr", "en", "de", "unknown"] = "unknown"
    keywords: list[Keyword] = Field(default_factory=list)
    answer_shape: AnswerShape = "single"
    answer_type: AnswerType = "text"
    structural_hints: StructuralHints = Field(default_factory=StructuralHints)
    decomposition: Decomposition = Field(default_factory=Decomposition)
    # Read by the absence builder when brick 2 flagged the question as vague.
    suggested_clarification: str | None = None
    ambiguity_reason: str | None = None
    candidate_values: list[str] = Field(default_factory=list)
    proposed_default: str | None = None


class Activation(BaseModel):
    model_config = ConfigDict(extra="allow")
    on: bool
    reason: str


class ExecutionPlan(BaseModel):
    """`activations` maps a flag name to {on, reason}; the dispatcher's names are the keys."""

    model_config = ConfigDict(extra="allow")
    activations: dict[str, Activation] = Field(default_factory=dict)


# The dispatcher's flags and the default the retrieval assumes when a plan does not carry them.
DEFAULT_ACTIVATIONS: dict[str, tuple[bool, str]] = {
    "use_keywords": (True, "keyword detectors always run"),
    "use_toc": (True, "default: the toc is a first-class signal"),
    "use_row_level": (False, "default: the question names no table column and asks for no amount or date"),
    "use_embeddings": (False, "no vocabulary mismatch expected beyond the dictionary; keywords prove absence"),
    "use_llm_arbiter": (False, "no key configured"),
    "use_llm_generation": (False, "no key configured"),
    "sweep_for_absence": (True, "always on"),
    "current_page_boost": (False, "no pages_hint"),
}


@dataclass
class Tables:
    """The brick-1 tables (SPEC §1). `parse_coverage` is the coverage JSON as a dict."""

    line_df: Any
    toc_df: Any
    row_df: Any = None
    corpus_index: Any = None
    page_df: Any = None
    cross_ref_df: Any = None
    parse_coverage: dict | None = None
    index_version: str | None = None
    extra: dict = field(default_factory=dict)


# --- duck-typed readers -------------------------------------------------------------------------


def attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` from an object or a mapping; missing gives `default`."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def as_tables(tables: Any) -> Tables:
    if isinstance(tables, Tables):
        return tables
    return Tables(
        line_df=attr(tables, "line_df"),
        toc_df=attr(tables, "toc_df"),
        row_df=attr(tables, "row_df"),
        corpus_index=attr(tables, "corpus_index"),
        page_df=attr(tables, "page_df"),
        cross_ref_df=attr(tables, "cross_ref_df"),
        parse_coverage=attr(tables, "parse_coverage"),
        index_version=attr(tables, "index_version"),
    )


def plan_activation(plan: Any, name: str) -> tuple[bool, str]:
    """(on, reason) of a flag; the plan may carry `activations[name]` or the flag as an attribute."""
    default_on, default_reason = DEFAULT_ACTIVATIONS.get(name, (False, "not in the plan"))
    activations = attr(plan, "activations")
    entry = attr(activations, name) if isinstance(activations, Mapping) else None
    if entry is None:
        entry = attr(plan, name)
    if entry is None or callable(entry):
        return default_on, default_reason
    if isinstance(entry, bool):
        return entry, f"plan flag {name} without a reason"
    on = attr(entry, "on", default_on)
    reason = attr(entry, "reason", default_reason)
    return bool(on), str(reason)


def plan_activations(plan: Any) -> dict[str, dict[str, Any]]:
    """Every known flag with its on/reason, for the `_meta` block."""
    names = list(DEFAULT_ACTIVATIONS)
    activations = attr(plan, "activations") or {}
    if callable(activations):  # brick 2's plan exposes activations() as a method
        try:
            activations = activations()
        except TypeError:
            activations = {}
    for name in (activations.keys() if isinstance(activations, Mapping) else []):
        if name not in names:
            names.append(name)
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        on, reason = plan_activation(plan, name)
        if isinstance(activations, Mapping) and name in activations:
            entry = activations[name]
            on, reason = bool(attr(entry, "on", on)), str(attr(entry, "reason", reason))
        out[name] = {"on": on, "reason": reason}
    return out


@dataclass(frozen=True)
class Term:
    """One question keyword, normalised for matching. `concept_key` groups variants of one concept."""

    text: str
    weight: float
    source: str
    concept: str | None
    is_regex: bool
    concept_key: str
    weak: bool = False
    in_corpus: bool = True  # brick 2's flag: False when no line of the corpus holds the word


def question_keywords(parsed: Any) -> list[Any]:
    return list(attr(parsed, "keywords", []) or [])


def question_text(parsed: Any) -> str:
    return str(attr(parsed, "corrected_question") or attr(parsed, "original_question") or "")


def question_terms(parsed: Any, variants_by_concept: Mapping[str, list[str]] | None = None) -> list[Term]:
    """The deduplicated keywords, each with its concept when the dictionary knows it.

    A direct keyword takes a concept when (a) brick 2 set it, (b) it is a variant of the concept
    (folded, then stem-equal for one-word variants), or (c) a multi-word variant of a concept named
    in the question contains it and occurs in the question ("responsabilité" and "civile" belong to
    responsabilite_civile when "responsabilité civile" is in the question). A generic word (text.WEAK_WORDS)
    weighs WEAK_WEIGHT.
    """
    variants_by_concept = variants_by_concept or {}
    ambiguous = ambiguous_variants(variants_by_concept)
    by_fold: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for concept, variants in variants_by_concept.items():
        for v in variants:
            if fold(v) in ambiguous:
                continue  # "assurance" names three concepts: it assigns none
            by_fold.setdefault(fold(v), concept)
            vs = stems(v)
            if len(vs) == 1:
                by_stem.setdefault(vs[0], concept)
    # (c): the stems of multi-word variants present in the question, for the concepts the question names.
    named = {str(attr(kw, "concept")) for kw in question_keywords(parsed) if attr(kw, "concept")}
    q_stems = stems(question_text(parsed))
    phrase_stem_concept: dict[str, str] = {}
    for concept in sorted(named):
        for v in variants_by_concept.get(concept, []):
            vs = stems(v)
            if len(vs) >= 2 and phrase_in(vs, q_stems):
                for s in vs:
                    phrase_stem_concept.setdefault(s, concept)

    seen: set[str] = set()
    terms: list[Term] = []
    for kw in question_keywords(parsed):
        text = str(attr(kw, "text", "") or "")
        is_regex = bool(attr(kw, "is_regex", False))
        key = text if is_regex else fold(text)
        if not key or key in seen:
            continue
        seen.add(key)
        source = str(attr(kw, "source", "direct") or "direct")
        concept = attr(kw, "concept")
        if not concept and not is_regex:
            ts = stems(text)
            concept = by_fold.get(fold(text)) or (by_stem.get(ts[0]) if len(ts) == 1 else None)
            if not concept and len(ts) == 1:
                concept = phrase_stem_concept.get(ts[0])
        weight = float(attr(kw, "weight", 1.0) or 1.0)
        weak = False
        if source == "direct" and not is_regex:
            weak = bool(attr(kw, "weak", False)) or weight < 0.5 or is_weak(text)
            if weak:
                weight = min(weight, WEAK_WEIGHT)
        concept_key = concept or ("regex:" + text if is_regex else " ".join(tokens(text)) or text)
        terms.append(Term(text=text, weight=weight, source=source, concept=concept, is_regex=is_regex,
                          concept_key=concept_key, weak=weak, in_corpus=bool(attr(kw, "in_corpus", True))))
    return terms


def concept_keys(terms: list[Term]) -> list[str]:
    """Distinct concept keys of the non-regex terms, in question order."""
    out: list[str] = []
    for t in terms:
        if not t.is_regex and t.concept_key not in out:
            out.append(t.concept_key)
    return out


@dataclass
class ContentWord:
    """A word the reader typed (a direct keyword) with every phrase that counts as it being covered."""

    text: str
    weight: float
    weak: bool
    concept_key: str
    phrases: list[list[str]]  # stems of the word itself and of every variant of its concept
    in_corpus: bool = True
    has_concept: bool = False


def ambiguous_variants(variants_by_concept: Mapping[str, list[str]]) -> set[str]:
    """The folded variants that belong to two or more concepts ("assurance", "registration")."""
    owners: dict[str, set[str]] = {}
    for concept, variants in variants_by_concept.items():
        for v in variants:
            owners.setdefault(fold(v), set()).add(concept)
    return {v for v, cs in owners.items() if len(cs) >= 2}


def content_words(terms: list[Term], variants_by_concept: Mapping[str, list[str]] | None = None) -> list[ContentWord]:
    """The direct keywords, each with its own stems and the stems of every variant of its concept
    (from the question's terms and from the dictionary). A variant shared by several concepts proves
    none of them, so it never stands in for another word."""
    variants_by_concept = variants_by_concept or {}
    ambiguous = ambiguous_variants(variants_by_concept)
    by_key: dict[str, list[list[str]]] = {}
    for t in terms:
        # The dictionary's expansions of a concept stand for its words; another word the reader typed
        # does not ("Santé" alone must not cover "complémentaire"). An ambiguous variant ("assurance")
        # stands only for itself.
        if t.source == "expert_dictionary" and not t.is_regex and stems(t.text) and fold(t.text) not in ambiguous:
            by_key.setdefault(t.concept_key, []).append(stems(t.text))
    for concept, variants in variants_by_concept.items():
        for v in variants:
            vs = stems(v)
            if vs and fold(v) not in ambiguous and vs not in by_key.setdefault(concept, []):
                by_key[concept].append(vs)
    words: list[ContentWord] = []
    for t in terms:
        if t.source != "direct" or t.is_regex or not stems(t.text):
            continue
        phrases = [stems(t.text)] + [p for p in by_key.get(t.concept_key, []) if p != stems(t.text)]
        words.append(ContentWord(text=t.text, weight=t.weight, weak=t.weak, concept_key=t.concept_key, phrases=phrases,
                                 in_corpus=t.in_corpus, has_concept=t.concept is not None))
    return words


_TITLE_STOP = frozenset(
    "le la les l un une des du de d au aux et ou a en pour par sur sous dans avec sans ce cet cette ces son sa ses "
    "qui que quoi dont qu il elle on ne pas plus est sont faut "
    "the a an and or of to in on at for with by from is are it its your what which how "
    "der die das den dem des ein eine und oder zu in an auf fur mit von bei ist sind".split()
)


def title_content_tokens(title: str) -> list[str]:
    """The words of a heading that carry its subject (brick 2's content_tokens when present)."""
    try:
        from guide_rag.question.normalize import content_tokens, fold_tokens

        return [t for t in content_tokens(fold_tokens(title)) if len(t) > 1]
    except Exception:  # brick 2 absent: a small stop list of the three languages
        return [t for t in tokens(title) if t not in _TITLE_STOP and len(t) > 1]


def title_exact(title: str, words: list[ContentWord]) -> bool:
    """"Trust the TOC on exact title matches": every content word of the heading is a word the
    reader typed (stem-equal to a direct word; dictionary variants do not count). "Étapes" is exact
    for "quelles sont les étapes…"; a FAQ question-heading with words of its own never is."""
    content = title_content_tokens(title)
    if not content or not words:
        return False
    typed = {s for w in words for s in w.phrases[0]}  # phrases[0] is the word itself
    return all(stem(fold(tw)) in typed for tw in content)


def concept_words(words: list[ContentWord]) -> list[ContentWord]:
    """The words a title must name to count as "an exact title match": the strong words carrying a
    dictionary concept; when the question names no concept, every strong word."""
    strong = [w for w in words if not w.weak]
    return [w for w in strong if w.has_concept] or strong


def coverage(words: list[ContentWord], stem_lists: Iterable[list[str]]) -> tuple[float, list[str], list[str]]:
    """(covered weight / total weight, covered words, uncovered words) over the given texts.

    A word is covered when any of its phrases appears whole in any of the texts.
    """
    lists = [s for s in stem_lists if s]
    total = sum(w.weight for w in words)
    covered: list[str] = []
    uncovered: list[str] = []
    for w in words:
        # A word brick 2 saw in no line of the corpus is uncovered unless a concept's variants stand for it
        # ("leave" is covered by "congé").
        hit = (w.in_corpus or w.has_concept) and any(phrase_in(p, ls) for p in w.phrases for ls in lists)
        (covered if hit else uncovered).append(w.text)
    if total <= 0:
        return 0.0, covered, uncovered
    got = sum(w.weight for w in words if w.text in covered)
    return round(got / total, 3), covered, uncovered


def hints(parsed: Any) -> tuple[list[str], str | None, str]:
    """(pages_hint, toc_section_hint, answer_context)."""
    sh = attr(parsed, "structural_hints")
    pages = attr(sh, "pages_hint") or []
    return list(pages), attr(sh, "toc_section_hint"), str(attr(sh, "answer_context", "paragraph") or "paragraph")


def concept_variants(dictionary: Any, parsed: Any = None) -> dict[str, list[str]]:
    """concept -> variants, from the dictionary in any of its shapes, merged with the question's own.

    Accepted shapes: {concept: [variant, ...]}, {concept: [{"keyword": ...}, ...]}, an object with
    `concept_variants()`, brick 2's Dictionary (`concept_keywords_df` or `concepts` + `variants_of`),
    or an object/mapping with `keywords` rows carrying `concept` and `keyword`.
    """
    out: dict[str, list[str]] = {}

    def add(concept: Any, variant: Any) -> None:
        if not concept or not variant:
            return
        bucket = out.setdefault(str(concept), [])
        v = str(variant)
        if v not in bucket:
            bucket.append(v)

    if dictionary is not None:
        if hasattr(dictionary, "concept_variants") and callable(dictionary.concept_variants):
            for c, vs in dictionary.concept_variants().items():
                for v in vs:
                    add(c, v)
        elif isinstance(dictionary, Mapping) and "keywords" not in dictionary:
            for c, vs in dictionary.items():
                for v in vs if isinstance(vs, (list, tuple)) else [vs]:
                    add(c, attr(v, "keyword", attr(v, "text", v)) if not isinstance(v, str) else v)
        elif getattr(dictionary, "concept_keywords_df", None) is not None:
            df = dictionary.concept_keywords_df
            for row in df[["concept", "keyword"]].to_dict("records"):
                add(row["concept"], row["keyword"])
        elif hasattr(dictionary, "variants_of") and hasattr(dictionary, "concepts"):
            for c in dictionary.concepts:
                for v in dictionary.variants_of(c):
                    add(c, attr(v, "keyword", attr(v, "text", v)))
        else:
            rows = attr(dictionary, "keywords", []) or []
            for row in rows:
                add(attr(row, "concept"), attr(row, "keyword", attr(row, "text")))
    for kw in question_keywords(parsed) if parsed is not None else []:
        if attr(kw, "is_regex", False):
            continue
        add(attr(kw, "concept"), attr(kw, "text"))
    return out


def stem_of(text: str) -> str:
    return stem(fold(text))
