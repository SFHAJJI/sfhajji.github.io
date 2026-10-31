"""dictionary/*.yaml and the loader: size, shape, matching, expansion."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from guide_rag.question.dictionary import TOPICS, Dictionary, match_key

DICTIONARY_DIR = Path(__file__).resolve().parents[1] / "dictionary"


@pytest.fixture(scope="module")
def dictionary() -> Dictionary:
    return Dictionary.load()


def test_dictionary_has_about_sixty_concepts_in_spec_topics(dictionary):
    size = dictionary.size()
    assert 75 <= size["concepts"] <= 120
    assert set(dictionary.concepts_df["topic"]) <= set(TOPICS)
    assert len(set(dictionary.concepts_df["topic"])) == len(TOPICS)  # every topic is covered


def test_every_concept_has_a_french_primary_and_an_english_variant(dictionary):
    kw = dictionary.concept_keywords_df
    for concept in dictionary.concepts:
        rows = kw[kw["concept"] == concept]
        assert ((rows["language"] == "fr") & (rows["priority"] == "primary")).any(), concept
        assert (rows["language"] == "en").any(), concept


def test_primary_variants_weigh_one_and_secondaries_less_or_equal(dictionary):
    kw = dictionary.concept_keywords_df
    assert (kw.loc[kw["priority"] == "primary", "weight"] == 1.0).all()
    assert (kw["weight"] <= 1.0).all() and (kw["weight"] > 0).all()


def test_no_duplicate_variant_per_concept_and_language(dictionary):
    kw = dictionary.concept_keywords_df.copy()
    kw["folded"] = kw["keyword"].str.lower()
    assert not kw.duplicated(["concept", "language", "folded"]).any()


def test_frames_have_the_spec_columns(dictionary):
    assert list(dictionary.concepts_df.columns) == ["concept", "topic", "definition"]
    assert list(dictionary.concept_keywords_df.columns) == ["concept", "language", "keyword", "priority", "weight"]


def test_match_key_is_folded_stemmed_content_words():
    assert match_key("fiche de retenue d'impôt") == ("fich", "retenu", "impot")
    assert match_key("RC") == ("rc",)


def test_match_concepts_prefers_the_longer_phrase(dictionary):
    matches = dictionary.match_concepts(["assurance", "auto"])
    assert [m.concept for m in matches] == ["assurance_auto"]
    bare = dictionary.match_concepts(["assurance"])
    assert {m.concept for m in bare} == {"assurance_auto", "mutuelle", "responsabilite_civile"}


def test_match_concepts_votes_once_per_concept_and_place(dictionary):
    matches = dictionary.match_concepts(["commune"])  # a French and an English variant
    assert len(matches) == 1 and matches[0].priority == "primary"


def test_match_is_accent_folded_and_stemmed(dictionary):
    assert [m.concept for m in dictionary.match_concepts(["controles", "techniques"])] == ["controle_technique"]
    assert [m.concept for m in dictionary.match_concepts(["etat", "lieux"])] == ["etat_des_lieux"]


def test_concepts_for_token_lists_the_ambiguity(dictionary):
    assert dictionary.concepts_for_token("registration") == [
        ("declaration_arrivee", "administration"),
        ("immatriculation", "vehicle"),
    ]
    assert dictionary.concepts_for_token("loyer") == [("loyer", "housing")]
    assert dictionary.concepts_for_token("zzz") == []


def test_expand_returns_every_variant_of_the_concepts_once(dictionary):
    variants = dictionary.expand(["bail", "bail", "loyer"])
    assert [v.concept for v in variants][: len(dictionary.variants_of("bail"))] == ["bail"] * len(dictionary.variants_of("bail"))
    assert {v.language for v in variants} >= {"fr", "en", "de"}
    assert len(variants) == len(dictionary.variants_of("bail")) + len(dictionary.variants_of("loyer"))


def test_label_of_falls_back_to_french(dictionary):
    assert dictionary.label_of("garantie_locative", "en") == "deposit"
    assert dictionary.label_of("garantie_locative", "unknown") == "garantie locative"


def test_loader_rejects_a_broken_dictionary():
    concepts = pd.DataFrame([("x", "nowhere", "d")], columns=["concept", "topic", "definition"])
    keywords = pd.DataFrame([("x", "fr", "x", "primary", 1.0)], columns=["concept", "language", "keyword", "priority", "weight"])
    with pytest.raises(ValueError):
        Dictionary(concepts, keywords)


def test_changelog_explains_the_seeding():
    text = (DICTIONARY_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "seed" in text.lower()
    assert "abbreviations.yaml" in text and "keywords.yaml" in text


def test_weak_words_file_has_three_languages():
    from guide_rag.question.normalize import WeakWords

    weak = WeakWords.load()
    assert weak.languages() == ["de", "en", "fr"]
    assert "documents" in weak and "document" in weak and "obtenir" in weak and "Unterlagen" in weak
    assert "immatriculation" not in weak


def test_tag_forms_cover_id_and_variants(dictionary):
    forms = dictionary.tag_forms("garantie_locative")
    assert {"garantie_locative", "garantie locative", "deposit", "garantie bancaire"} <= forms


def test_single_word_keys_shared_across_topics_are_the_known_ambiguities(dictionary):
    """Only the generic words meant to trigger a clarification may be shared across topics."""
    by_key: dict[str, set[str]] = {}
    for v in dictionary._variants:
        if len(v.key) == 1:
            by_key.setdefault(v.key[0], set()).add(v.topic)
    shared = sorted(k for k, topics in by_key.items() if len(topics) > 1)
    assert shared == ["assuranc", "insuranc", "registration"]


TOOL_PAGES = {"accueil", "admin", "assistant", "carte", "cartes", "comparateur", "faq", "fiches", "jeux", "parcours"}


def test_every_document_title_of_the_real_index_reaches_a_concept(dictionary):
    """The grown dictionary covers the 50 titles; tool pages have no subject of their own."""
    import json

    from guide_rag.question.normalize import content_tokens, fold_tokens

    index_path = Path(__file__).resolve().parents[1] / "index" / "corpus_index.json"
    if not index_path.exists():
        pytest.skip("index/corpus_index.json not built")
    rows = json.loads(index_path.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", rows)
    missing = [
        r["doc_id"]
        for r in rows
        if r["doc_id"] not in TOOL_PAGES and not dictionary.match_concepts(content_tokens(fold_tokens(r["title"])))
    ]
    assert missing == []
