"""normalize.py: folding, tokens, vocabulary and spell correction, abbreviations, language."""

from __future__ import annotations

import pandas as pd
import pytest

from guide_rag.question.normalize import (
    Abbreviations,
    Vocabulary,
    damerau_levenshtein,
    detect_language,
    fold,
    normalize_question,
    tokenize,
)
from guide_rag.question.stopwords import stem

try:
    from test_question_fixtures import synthetic_tables  # pytest puts tests/ on sys.path
except ImportError:  # pragma: no cover - when tests/ becomes a package
    from tests.test_question_fixtures import synthetic_tables


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return Vocabulary.from_line_df(synthetic_tables()["line_df"])


def test_fold_strips_accents_and_case_only():
    assert fold("Contrôle Technique à Lëtzebuerg œuvre") == "controle technique a letzebuerg oeuvre"


def test_tokenize_splits_apostrophes_and_hyphens_and_keeps_accents():
    assert tokenize("L'état-des-lieux d’entrée") == ["l", "état", "des", "lieux", "d", "entrée"]


def test_stem_is_light_and_stable():
    assert stem("locatives") == stem("locative") == "locativ"
    assert stem("animaux") == "animal"
    assert stem("class") == "class" and stem("classes") == "class"
    assert stem("bail") == "bail"  # short tokens untouched


def test_damerau_levenshtein_counts_transpositions_once():
    assert damerau_levenshtein("immatriculation", "imatriculation") == 1
    assert damerau_levenshtein("garantie", "garnatie") == 1
    assert damerau_levenshtein("abc", "xyz", 2) == 3  # early exit above the cap


def test_vocabulary_is_built_from_line_df(vocabulary):
    assert "immatriculation" in vocabulary
    assert vocabulary.frequency("immatriculation") == 2
    assert vocabulary.display("vehicule") == "véhicule"  # the corpus spelling is kept for display


def test_typo_is_corrected_against_the_corpus(vocabulary):
    found = vocabulary.lookup("imatriculation")
    assert found is not None and found.corrected == "immatriculation" and found.distance == 1
    assert vocabulary.correct("garantie") == "garantie"


def test_known_token_is_never_corrected(vocabulary):
    assert vocabulary.lookup("loyer") is None
    assert vocabulary.lookup("Véhicule") is None


def test_token_with_nothing_close_is_kept(vocabulary):
    assert vocabulary.lookup("kindergarten") is None
    assert vocabulary.correct("kindergarten") == "kindergarten"


def test_short_tokens_digits_and_stop_word_targets_are_never_corrected():
    vocabulary = Vocabulary.from_texts(["votre voiture est là", "le code 1648"])
    assert vocabulary.lookup("rc") is None  # too short
    assert vocabulary.lookup("1649") is None  # digits
    assert vocabulary.lookup("code") is None  # four letters: never corrected
    assert vocabulary.lookup("voitre") is None or vocabulary.lookup("voitre").corrected != "votre"


def test_dictionary_terms_are_known_but_not_correction_targets():
    vocabulary = Vocabulary.from_texts(["cette page du guide"], known_terms=["fiche de paie", "immatriculation"])
    assert "immatriculation" in vocabulary
    assert vocabulary.lookup("immatriculation") is None  # known, never corrected
    assert vocabulary.lookup("paie") is None  # known
    assert vocabulary.lookup("pageo") is None or vocabulary.lookup("pageo").corrected == "page"


def test_abbreviations_load_and_expand():
    abbreviations = Abbreviations.load()
    assert len(abbreviations) >= 15
    assert abbreviations.get("RC").expansion == "responsabilité civile"
    assert abbreviations.get("cns").expansion == "caisse nationale de santé"
    assert abbreviations.get("CT").expansion == "contrôle technique"
    assert "ccss" in abbreviations and "adem" in abbreviations


def test_normalize_expands_abbreviations_before_spelling(vocabulary):
    n = normalize_question("Dois-je faire le CT de ma voiture ?", vocabulary=vocabulary)
    assert n.corrected == "dois-je faire le contrôle technique de ma voiture ?"
    assert n.expansions == [("ct", "contrôle technique")]
    assert n.corrections == []
    assert n.content == ["controle", "technique", "voiture"]


def test_normalize_keeps_punctuation_and_the_original(vocabulary):
    n = normalize_question("Imatriculation : combien ?", vocabulary=vocabulary)
    assert n.original == "Imatriculation : combien ?"
    assert n.corrected == "immatriculation : combien ?"


@pytest.mark.parametrize(
    "question, language",
    [
        ("Comment faire pour la garantie locative ?", "fr"),
        ("How do I get the registration certificate?", "en"),
        ("Wie bekomme ich den Führerschein?", "de"),
        ("immatriculation", "unknown"),
    ],
)
def test_language_by_stop_word_vote(question, language):
    assert normalize_question(question).language == language


def test_language_tie_breaker_uses_extra_votes():
    assert detect_language(["garantie", "locative"]) == "unknown"
    assert detect_language(["garantie", "locative"], {"fr": 1}) == "fr"


def test_pronouns_are_seen():
    n = normalize_question("et pour celui-là ?")
    assert "celui-la" in n.pronouns_seen
    assert n.content == []


def test_vocabulary_from_empty_frame_is_empty():
    assert len(Vocabulary.from_line_df(pd.DataFrame(columns=["doc_id", "text"]))) == 0
    assert len(Vocabulary.from_line_df(None)) == 0
