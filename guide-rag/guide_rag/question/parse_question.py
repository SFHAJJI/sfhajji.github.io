"""Brick 2: the question becomes a `ParsedQuestion` row. Deterministic, model-free.

Every decision leaves a sentence in `parsing_notes`, so the trace panel can show why a keyword,
a shape or a clarification exists. Same question, same tables, same row.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Literal

import pandas as pd
from pydantic import BaseModel, Field

from guide_rag.question.dictionary import ConceptMatch, Dictionary
from guide_rag.question.normalize import (
    Abbreviations,
    NormalizedQuestion,
    Vocabulary,
    WeakWords,
    content_tokens,
    damerau_levenshtein,
    detect_language,
    fold,
    fold_tokens,
    normalize_question,
)
from guide_rag.question.stopwords import stem

Language = Literal["fr", "en", "de", "unknown"]
AnswerShape = Literal["single", "listing"]
AnswerType = Literal["text", "amount", "date", "boolean", "address", "phone", "url", "duration"]
AnswerContext = Literal["line", "paragraph", "section"]
KeywordSource = Literal["direct", "expert_dictionary", "anchor"]
AmbiguityReason = Literal["too_short", "no_content_words", "pronoun_only", "single_term_multiple_concepts"]

DICTIONARY_WEIGHT = 0.6  # SPEC §2: every variant of a matched concept


# ----------------------------------------------------------------------------- the model


class Keyword(BaseModel):
    text: str
    weight: float
    source: KeywordSource
    concept: str | None = None
    is_regex: bool = False
    weak: bool = False  # a generic verb or noun of dictionary/weak_words.yaml: weight 0.3, never decides
    in_corpus: bool = True  # False when no line of the corpus holds the word: the sweep reports 0 hits


WEAK_WEIGHT = 0.3


class StructuralHints(BaseModel):
    pages_hint: list[str] | None = None
    toc_section_hint: str | None = None
    answer_context: AnswerContext = "paragraph"


class ScopeFilters(BaseModel):
    topic: str | None = None


class Decomposition(BaseModel):
    pattern: Literal["single", "independent"] = "single"
    sub_questions: list[str] = Field(default_factory=list)


class ParsedQuestion(BaseModel):
    question_id: str
    original_question: str
    corrected_question: str
    language: Language
    keywords: list[Keyword]
    answer_shape: AnswerShape
    answer_type: AnswerType
    structural_hints: StructuralHints
    scope_filters: ScopeFilters
    decomposition: Decomposition
    suggested_clarification: str | None = None
    ambiguity_reason: AmbiguityReason | None = None
    candidate_values: list[str] = Field(default_factory=list)
    proposed_default: str | None = None
    parsing_notes: list[str] = Field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return self.ambiguity_reason is not None

    @property
    def concepts(self) -> list[str]:
        seen: list[str] = []
        for k in self.keywords:
            if k.concept and k.concept not in seen:
                seen.append(k.concept)
        return seen


def question_id_of(original: str) -> str:
    return hashlib.sha1(original.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------- cue tables
# Cues are matched on the folded corrected question (lowercase, no accents), whole words.

LISTING_CUES = (
    # fr
    "quels", "quelles", "lesquels", "lesquelles", "liste", "lister", "listez", "enumerer", "enumere",
    "toutes les", "tous les", "les etapes", "etapes", "pieces a fournir", "documents necessaires",
    "documents a fournir", "quelles sont", "quels sont",
    # en
    "which", "what are", "list", "all the", "all of", "steps", "documents needed", "documents required",
    "what documents", "requirements",
    # de
    "welche", "welches", "liste", "alle", "schritte", "unterlagen", "dokumente",
)

BOOLEAN_FRAMES = (
    "est-ce que", "est ce que", "est-ce qu", "est ce qu", "dois-je", "dois je", "doit-on", "doit on",
    "puis-je", "puis je", "peut-on", "peut on", "faut-il", "faut il", "y a-t-il", "y a t il", "ai-je",
    "suis-je", "est-il", "est-elle", "est il", "est elle", "a-t-on", "peux-je",
    "can i", "could i", "do i", "does", "must i", "should i", "is it", "is the", "is there", "are there",
    "am i", "will i", "can we", "may i", "do we", "are the", "have i",
    "muss ich", "kann ich", "darf ich", "soll ich", "ist es", "gibt es", "brauche ich", "ist die",
    "ist der", "ist das", "mussen wir", "konnen wir",
)

DURATION_CUES = (
    "combien de temps", "duree", "delai", "delais", "validite", "valable", "pendant combien",
    "how long", "duration", "validity", "valid for", "how many days", "how many months", "how many years",
    "wie lange", "dauer", "gultig", "gultigkeit", "frist",
)
AMOUNT_CUES = (
    "combien", "coute", "coutent", "cout", "couts", "prix", "montant", "tarif", "tarifs", "frais", "euros",
    "euro", "€",
    "how much", "cost", "costs", "price", "fee", "fees", "amount",
    "wie viel", "wieviel", "wie hoch", "kostet", "kosten", "preis", "gebuhr", "gebuhren", "betrag", "betragt",
)
DATE_CUES = (
    "quand", "quelle date", "a partir de quand", "jusqu a quand", "echeance", "date limite", "date",
    "when", "deadline", "by when", "what date",
    "wann", "datum", "ab wann", "bis wann", "stichtag",
)
PHONE_CUES = (
    "telephone", "numero de telephone", "appeler", "tel", "hotline",
    "phone", "phone number", "call", "telephone number",
    "telefon", "telefonnummer", "anrufen",
)
ADDRESS_CUES = (
    "adresse", "se trouve", "situe", "situee", "ou aller", "ou se rendre",
    "address", "where is", "where are", "located", "where do i go", "where can i go",
    "wo ist", "wo befindet", "wo sind", "wohin",
)
URL_CUES = (
    "site", "site web", "site internet", "lien", "url",
    "website", "link", "web page", "webpage",
    "webseite", "internetseite",
)

PAGE_REFERENCE_CUES = ("sur cette page", "cette page", "on this page", "this page", "auf dieser seite", "diese seite")

INTERROGATIVES = frozenset(
    """
    comment quand combien ou quel quelle quels quelles pourquoi que quoi qui
    how when where which what why who
    wie wann wo welche welcher welches warum was wer
    """.split()
)

MONTHS = (
    "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre|"
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "januar|februar|m[aä]rz|juni|juli|oktober|dezember"
)

# Anchor patterns per answer type (SPEC §2: amount €, date, phone, postal code, form codes).
ANCHOR_PATTERNS: dict[str, str] = {
    "amount": r"(?:\d{1,3}(?:[ .]\d{3})+|\d+)(?:[.,]\d+)?\s?(?:€|euros?|eur)\b",
    "date": rf"\b\d{{1,2}}(?:er)?\s+(?:{MONTHS})\s+\d{{4}}\b|\b\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}\b|\b(?:{MONTHS})\s+\d{{4}}\b",
    "phone": r"(?:\+352|00352)?\s?(?:\d[\s.-]?){5,9}\d\b",
    "address": r"\bL-?\s?\d{4}\b",
    "url": r"https?://\S+|\b[\w-]+\.(?:lu|com|eu|org|net)\b",
    "duration": r"\b\d+\s?(?:jours?|mois|ans?|annees?|semaines?|heures?|days?|months?|years?|weeks?|hours?|tagen?|monaten?|jahren?|wochen?)\b",
}


# ----------------------------------------------------------------------------- helpers


def _has_cue(folded_text: str, cues: Iterable[str]) -> str | None:
    """The first cue present as a whole word or phrase, else None."""
    padded = f" {folded_text} "
    for cue in cues:
        if cue == "€":
            if "€" in folded_text:
                return cue
            continue
        if re.search(rf"(?<![\w-]){re.escape(cue)}(?![\w-])", padded):
            return cue
    return None


def _starts_with_frame(folded_text: str, frames: Iterable[str]) -> str | None:
    stripped = folded_text.lstrip(" ¿?!,.;:'\"")
    for frame in frames:
        if stripped.startswith(frame + " ") or stripped == frame or stripped.startswith(frame + "'"):
            return frame
    return None


def _answer_shape(folded_text: str) -> tuple[AnswerShape, str]:
    cue = _has_cue(folded_text, LISTING_CUES)
    if cue:
        return "listing", f"answer_shape=listing: cue '{cue}'"
    return "single", "answer_shape=single: no listing cue"


def _answer_type(folded_text: str) -> tuple[AnswerType, str]:
    frame = _starts_with_frame(folded_text, BOOLEAN_FRAMES)
    if frame:
        return "boolean", f"answer_type=boolean: the question opens with '{frame}'"
    ordered: tuple[tuple[AnswerType, tuple[str, ...]], ...] = (
        ("duration", DURATION_CUES),
        ("amount", AMOUNT_CUES),
        ("date", DATE_CUES),
        ("phone", PHONE_CUES),
        ("address", ADDRESS_CUES),
        ("url", URL_CUES),
    )
    for answer_type, cues in ordered:
        cue = _has_cue(folded_text, cues)
        if cue:
            return answer_type, f"answer_type={answer_type}: cue '{cue}'"
    for answer_type, pattern in ANCHOR_PATTERNS.items():
        if answer_type in ("amount", "date", "phone") and re.search(pattern, folded_text):
            return answer_type, f"answer_type={answer_type}: the question itself holds a {answer_type} pattern"  # type: ignore[return-value]
    return "text", "answer_type=text: no typed cue"


def _answer_context(answer_shape: AnswerShape, answer_type: AnswerType) -> AnswerContext:
    if answer_shape == "listing":
        return "section"
    if answer_type in ("amount", "date", "boolean", "phone", "url", "duration"):
        return "line"
    return "paragraph"


def _doc_ids(frame: pd.DataFrame | None) -> set[str]:
    if frame is None or len(frame) == 0 or "doc_id" not in frame.columns:
        return set()
    return set(frame["doc_id"].astype(str))


def _tags_of(row) -> list[str]:
    """`corpus_index.tags` may be a list, a JSON-ish string or a comma-separated string."""
    tags = getattr(row, "tags", None)
    if tags is None or (isinstance(tags, float) and pd.isna(tags)):
        return []
    if isinstance(tags, str):
        return [t.strip(" '\"[]") for t in tags.split(",") if t.strip(" '\"[]")]
    return [str(t) for t in tags]


def _toc_section_hint(
    stems: list[str], toc_df: pd.DataFrame | None, current_page: str | None
) -> tuple[str | None, str | None]:
    """The heading whose every content word is in the question (fuzzy by one edit on long words).

    Longest heading wins; a tie goes to the reader's page, then to the first row of toc_df.
    """
    if toc_df is None or len(toc_df) == 0 or "title" not in toc_df.columns or not stems:
        return None, None
    question_stems = set(stems)
    best: tuple[int, int, int, str] | None = None  # (-n_tokens, not_on_page, row_order, title)
    for order, row in enumerate(toc_df.itertuples(index=False)):
        title = str(row.title)
        title_stems = [stem(t) for t in content_tokens(fold_tokens(title))]
        if not title_stems:
            continue
        if not all(_stem_in(s, question_stems) for s in title_stems):
            continue
        if len(title_stems) == 1 and len(title_stems[0]) < 4:
            continue  # a one-word heading of three letters is too easy to hit by accident
        on_page = 0 if current_page is not None and str(getattr(row, "doc_id", "")) == current_page else 1
        key = (-len(title_stems), on_page, order, title)
        if best is None or key < best:
            best = key
    if best is None:
        return None, None
    title = best[3]
    return title, f"toc_section_hint='{title}': every word of this heading is in the question"


def _stem_in(s: str, stems: set[str]) -> bool:
    if s in stems:
        return True
    if len(s) >= 6:
        return any(len(q) >= 6 and damerau_levenshtein(s, q, 1) <= 1 for q in stems)
    return False


def _decompose(corrected: str) -> tuple[Decomposition, str]:
    """The "et / and" test: two clauses that each carry a subject are two questions."""
    parts = [p.strip(" ?!.;,") for p in re.split(r"\s+(?:et|and|und)\s+|\s*;\s*", corrected) if p.strip(" ?!.;,")]
    if len(parts) < 2:
        return Decomposition(), "decomposition=single: no 'et / and' between two clauses"
    for part in parts:
        folded = fold_tokens(part)
        content = content_tokens(folded)
        has_interrogative = any(t in INTERROGATIVES for t in folded)
        if not (len(content) >= 2 or (len(content) >= 1 and has_interrogative)):
            return Decomposition(), f"decomposition=single: '{part}' is not a clause of its own"
    return (
        Decomposition(pattern="independent", sub_questions=parts),
        f"decomposition=independent: {len(parts)} clauses, each with its own content words",
    )


def _clarification_text(
    language: str, reason: AmbiguityReason, term: str, labels: list[str], default_label: str | None
) -> str:
    lang = language if language in ("fr", "en", "de") else "fr"
    options = ", ".join(labels)
    texts = {
        "fr": {
            "too_short": "Votre question est trop courte. Dites-moi ce que vous cherchez, par exemple « comment immatriculer ma voiture ? ».",
            "no_content_words": "Je ne vois pas de mot-clé dans votre question. De quel sujet du guide s'agit-il ?",
            "pronoun_only": f"« {term} » ne me dit pas de quoi il s'agit. De quel sujet du guide parlez-vous ?",
            "single_term_multiple_concepts": f"« {term} » peut vouloir dire : {options}. Je propose « {default_label} » ; précisez si vous pensiez à autre chose.",
        },
        "en": {
            "too_short": "Your question is too short. Tell me what you are looking for, for example 'how do I register my car?'.",
            "no_content_words": "I see no keyword in your question. Which subject of the guide do you mean?",
            "pronoun_only": f"'{term}' does not tell me what it is. Which subject of the guide do you mean?",
            "single_term_multiple_concepts": f"'{term}' can mean: {options}. I propose '{default_label}'; say so if you meant another one.",
        },
        "de": {
            "too_short": "Ihre Frage ist zu kurz. Sagen Sie mir, was Sie suchen, zum Beispiel 'wie melde ich mein Auto an?'.",
            "no_content_words": "Ich sehe kein Stichwort in Ihrer Frage. Welches Thema des Leitfadens meinen Sie?",
            "pronoun_only": f"'{term}' sagt mir nicht, worum es geht. Welches Thema des Leitfadens meinen Sie?",
            "single_term_multiple_concepts": f"'{term}' kann bedeuten: {options}. Ich schlage '{default_label}' vor; sagen Sie es, wenn Sie etwas anderes meinten.",
        },
    }
    return texts[lang][reason]


def _proposed_default(
    candidates: list[tuple[str, str]],
    dictionary: Dictionary,
    corpus_index: pd.DataFrame | None,
    current_page: str | None,
) -> tuple[str, str]:
    """The candidate whose topic is the reader's page, else the one most pages are tagged with."""
    page_topic: str | None = None
    if current_page is not None and corpus_index is not None and len(corpus_index) and "topic" in corpus_index.columns:
        rows = corpus_index[corpus_index["doc_id"].astype(str) == current_page]
        if len(rows):
            page_topic = str(rows.iloc[0]["topic"])
    if page_topic is not None:
        on_page = [c for c, t in candidates if t == page_topic]
        if on_page:
            return on_page[0], f"its topic '{page_topic}' is the topic of the page being read ({current_page})"
    # A tag counts for a candidate when it is the concept id or any of its variants, folded: the
    # index writes "declaration d'arrivee" where the dictionary says declaration_arrivee.
    counts = {c: 0 for c, _ in candidates}
    forms = {c: dictionary.tag_forms(c) for c, _ in candidates}
    if corpus_index is not None and len(corpus_index) and "tags" in corpus_index.columns:
        for row in corpus_index.itertuples(index=False):
            tags = {fold(t) for t in _tags_of(row)}
            for concept, concept_forms in forms.items():
                if tags & concept_forms:
                    counts[concept] += 1
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if best[1] == 0:
        return best[0], "no page of the corpus is tagged with any candidate; first candidate by name"
    return best[0], f"{best[1]} page(s) of the corpus are tagged with it, more than any other candidate"


_VOCABULARY_CACHE: dict[tuple[int, int], Vocabulary] = {}
_WEAK_WORDS: WeakWords | None = None


def weak_words() -> WeakWords:
    """`dictionary/weak_words.yaml`, read once per process."""
    global _WEAK_WORDS
    if _WEAK_WORDS is None:
        _WEAK_WORDS = WeakWords.load()
    return _WEAK_WORDS


def vocabulary_for(line_df: pd.DataFrame | None, dictionary: Dictionary | None = None) -> Vocabulary:
    """The corpus vocabulary, built once per `line_df` object; dictionary words count as known."""
    key = (id(line_df), 0 if line_df is None else len(line_df))
    cached = _VOCABULARY_CACHE.get(key)
    if cached is not None:
        return cached
    known = dictionary.terms() if dictionary is not None else []
    vocabulary = Vocabulary.from_line_df(line_df, known_terms=known)
    _VOCABULARY_CACHE[key] = vocabulary
    return vocabulary


# ----------------------------------------------------------------------------- the parser


def parse_question(
    question: str,
    *,
    line_df: pd.DataFrame | None,
    toc_df: pd.DataFrame | None,
    corpus_index: pd.DataFrame | None,
    dictionary: Dictionary,
    current_page: str | None = None,
    vocabulary: Vocabulary | None = None,
    abbreviations: Abbreviations | None = None,
    weak: WeakWords | None = None,
) -> ParsedQuestion:
    """Normalise, detect, extract, decompose, and decide whether to ask one clarification."""
    notes: list[str] = []
    vocabulary = vocabulary or vocabulary_for(line_df, dictionary)
    weak = weak or weak_words()
    normalized: NormalizedQuestion = normalize_question(question, vocabulary=vocabulary, abbreviations=abbreviations)
    for short, long in normalized.expansions:
        notes.append(f"abbreviation '{short}' expanded to '{long}'")
    for c in normalized.corrections:
        notes.append(f"spelling '{c.original}' corrected to '{c.display}' (distance {c.distance}, corpus frequency {c.frequency})")

    folded_text = normalized.folded
    matches = dictionary.match_concepts(normalized.content)
    language = normalized.language
    if language == "unknown":
        votes: dict[str, int] = {}
        for m in matches:
            votes[m.language] = votes.get(m.language, 0) + 1
        language = detect_language(normalized.folded_tokens, votes)
        if language != "unknown":
            notes.append(f"language={language}: no stop word voted, the matched dictionary variants did")
        else:
            notes.append("language=unknown: no stop word and no dictionary variant voted")
    else:
        notes.append(f"language={language}: stop-word vote")

    # -- shape, type, context
    answer_shape, note = _answer_shape(folded_text)
    notes.append(note)
    answer_type, note = _answer_type(folded_text)
    notes.append(note)
    answer_context = _answer_context(answer_shape, answer_type)

    # -- keywords
    keywords: list[Keyword] = []
    seen_folded: set[str] = set()
    surface_by_folded: dict[str, str] = {}
    for token, folded in zip(normalized.tokens, normalized.folded_tokens):
        surface_by_folded.setdefault(folded, token)
    strong: list[str] = []  # content words that are not weak: the ones that can carry a subject
    for folded in normalized.content:
        if folded in seen_folded or folded.isdigit():
            continue
        seen_folded.add(folded)
        is_weak = folded in weak
        in_corpus = vocabulary.frequency(folded) > 0
        if not is_weak:
            strong.append(folded)
        # A word absent from the corpus stays a keyword at full weight: the absence sweep must
        # be able to report zero hits for "sapin" or "noël", not silently drop them.
        if not in_corpus:
            notes.append(f"'{surface_by_folded.get(folded, folded)}' is in no line of the corpus (kept, in_corpus=false)")
        keywords.append(
            Keyword(
                text=surface_by_folded.get(folded, folded),
                weight=WEAK_WEIGHT if is_weak else 1.0,
                source="direct",
                weak=is_weak,
                in_corpus=in_corpus,
            )
        )
    if any(k.weak for k in keywords):
        notes.append("weak words (weight 0.3): " + ", ".join(k.text for k in keywords if k.weak))
    for m in matches:
        notes.append(f"concept '{m.concept}' ({m.topic}) matched by '{m.keyword}' [{m.language}, {m.priority}]")
    for variant in dictionary.expand(matches):
        text = variant.keyword.lower()
        folded = fold(text)
        if folded in seen_folded:
            continue
        seen_folded.add(folded)
        keywords.append(
            Keyword(
                text=text,
                weight=round(DICTIONARY_WEIGHT * variant.weight, 3),
                source="expert_dictionary",
                concept=variant.concept,
                in_corpus=all(vocabulary.frequency(t) > 0 for t in content_tokens(fold_tokens(text))),
            )
        )
    if answer_type in ANCHOR_PATTERNS:
        keywords.append(Keyword(text=ANCHOR_PATTERNS[answer_type], weight=1.0, source="anchor", is_regex=True))
        notes.append(f"anchor regex for {answer_type} added")
    for folded in normalized.content:
        if folded.isdigit() and rf"\b{folded}\b" not in seen_folded:
            seen_folded.add(rf"\b{folded}\b")
            keywords.append(Keyword(text=rf"\b{folded}\b", weight=1.0, source="anchor", is_regex=True))
            notes.append(f"anchor for the number '{folded}' typed in the question")

    # -- structural hints
    pages_hint: list[str] | None = None
    page_cue = _has_cue(folded_text, PAGE_REFERENCE_CUES)
    if current_page:
        pages_hint = [current_page]
        known_pages = _doc_ids(corpus_index) | _doc_ids(toc_df) | _doc_ids(line_df)
        if known_pages and current_page not in known_pages:
            notes.append(f"pages_hint=['{current_page}'] from the reader's page, which the tables do not list")
        else:
            notes.append(f"pages_hint=['{current_page}'] from the reader's page" + (f" ('{page_cue}' confirms it)" if page_cue else ""))
    elif page_cue:
        notes.append(f"the question says '{page_cue}' but no current page was given: pages_hint stays empty")
    section_hint, note = _toc_section_hint(normalized.stems(), toc_df, current_page)
    if note:
        notes.append(note)

    # -- topic
    topic, note = _topic_of(matches, corpus_index, current_page)
    notes.append(note)

    # -- decomposition
    decomposition, note = _decompose(normalized.corrected)
    notes.append(note)

    # -- clarification
    ambiguity: AmbiguityReason | None = None
    clarification: str | None = None
    candidate_values: list[str] = []
    proposed_default: str | None = None
    term = ""
    if len(question.strip()) < 2 or not normalized.tokens:
        ambiguity = "too_short"
    elif not normalized.content and normalized.pronouns_seen:
        ambiguity = "pronoun_only"
        term = surface_by_folded.get(normalized.pronouns_seen[0], normalized.pronouns_seen[0])
    elif not normalized.content:
        ambiguity = "no_content_words"
    elif not strong and not matches:
        # "comment obtenir des documents ?": only weak words and no concept, so no subject;
        # "ça marche comment ?": the same, but a pronoun stands where the subject should be.
        if normalized.pronouns_seen:
            ambiguity = "pronoun_only"
            term = surface_by_folded.get(normalized.pronouns_seen[0], normalized.pronouns_seen[0])
            notes.append("every content word is a weak word and a pronoun stands for the subject")
        else:
            ambiguity = "no_content_words"
            notes.append("every content word is a weak word: no subject")
    elif len(strong) == 1:
        candidates = dictionary.concepts_for_token(strong[0])
        if len({t for _, t in candidates}) >= 2:
            ambiguity = "single_term_multiple_concepts"
            term = surface_by_folded.get(strong[0], strong[0])
            candidate_values = [c for c, _ in candidates]
            proposed_default, why = _proposed_default(candidates, dictionary, corpus_index, current_page)
            notes.append(f"proposed_default='{proposed_default}': {why}")
            topic = dictionary.topic_of(proposed_default)
            notes.append(f"scope topic '{topic}' follows the proposed default until the reader says otherwise")
    if ambiguity is not None:
        labels = [f"{dictionary.label_of(c, language)} ({dictionary.topic_of(c)})" for c in candidate_values]
        default_label = dictionary.label_of(proposed_default, language) if proposed_default else None
        clarification = _clarification_text(language, ambiguity, term, labels, default_label)
        notes.append(f"clarification: {ambiguity}")

    return ParsedQuestion(
        question_id=question_id_of(question),
        original_question=question,
        corrected_question=normalized.corrected,
        language=language,  # type: ignore[arg-type]
        keywords=keywords,
        answer_shape=answer_shape,
        answer_type=answer_type,
        structural_hints=StructuralHints(pages_hint=pages_hint, toc_section_hint=section_hint, answer_context=answer_context),
        scope_filters=ScopeFilters(topic=topic),
        decomposition=decomposition,
        suggested_clarification=clarification,
        ambiguity_reason=ambiguity,
        candidate_values=candidate_values,
        proposed_default=proposed_default,
        parsing_notes=notes,
    )


def _topic_of(
    matches: list[ConceptMatch], corpus_index: pd.DataFrame | None, current_page: str | None
) -> tuple[str | None, str]:
    """The topic the matched concepts vote for, weighted by variant weight; the page breaks ties."""
    if not matches:
        return None, "scope topic=None: no dictionary concept matched"
    votes: dict[str, float] = {}
    for m in matches:
        votes[m.topic] = round(votes.get(m.topic, 0.0) + m.weight, 3)
    top = max(votes.values())
    leaders = sorted(t for t, v in votes.items() if v == top)
    if len(leaders) == 1:
        return leaders[0], f"scope topic='{leaders[0]}': the matched concepts vote {votes}"
    if current_page is not None and corpus_index is not None and len(corpus_index) and "topic" in corpus_index.columns:
        rows = corpus_index[corpus_index["doc_id"].astype(str) == current_page]
        if len(rows) and str(rows.iloc[0]["topic"]) in leaders:
            page_topic = str(rows.iloc[0]["topic"])
            return page_topic, f"scope topic='{page_topic}': a tie {leaders}, broken by the page being read"
    return None, f"scope topic=None: a tie between {leaders} and no page to break it"
