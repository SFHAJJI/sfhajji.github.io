"""parse_question.py over the synthetic tables: every field of ParsedQuestion has a test."""

from __future__ import annotations

import hashlib

import pytest

from guide_rag.question import ParsedQuestion, parse_question

try:
    from test_question_fixtures import dictionary, tables  # noqa: F401  (fixtures)
except ImportError:  # pragma: no cover
    from tests.test_question_fixtures import dictionary, tables  # noqa: F401


@pytest.fixture
def parse(tables, dictionary):
    def _parse(question: str, current_page: str | None = None) -> ParsedQuestion:
        return parse_question(
            question,
            line_df=tables["line_df"],
            toc_df=tables["toc_df"],
            corpus_index=tables["corpus_index"],
            dictionary=dictionary,
            current_page=current_page,
        )

    return _parse


# -- normalisation inside the parser


def test_typo_is_corrected_and_noted(parse):
    p = parse("imatriculation voiture")
    assert p.corrected_question == "immatriculation voiture"
    assert any("imatriculation" in n and "immatriculation" in n for n in p.parsing_notes)
    assert p.scope_filters.topic == "vehicle"
    assert "immatriculation" in [k.text for k in p.keywords if k.source == "direct"]


def test_abbreviation_rc_is_expanded_and_kept_as_dictionary_keyword(parse):
    p = parse("Est-ce que je dois prendre une RC ?")
    assert "responsabilité civile" in p.corrected_question
    assert "responsabilite_civile" in p.concepts
    rc = [k for k in p.keywords if k.text == "rc"]
    assert rc and rc[0].source == "expert_dictionary" and rc[0].concept == "responsabilite_civile"


def test_question_id_is_sha1_of_the_original(parse):
    q = "Combien coûte la garantie locative ?"
    assert parse(q).question_id == hashlib.sha1(q.encode("utf-8")).hexdigest()[:16]
    assert parse(q).original_question == q


# -- languages


@pytest.mark.parametrize(
    "question, language, concept",
    [
        ("Combien coûte la garantie locative ?", "fr", "garantie_locative"),
        ("How much is the rental deposit?", "en", "garantie_locative"),
        ("Wie hoch ist die Mietkaution?", "de", "garantie_locative"),
    ],
)
def test_fr_en_de_reach_the_same_concept(parse, question, language, concept):
    p = parse(question)
    assert p.language == language
    assert concept in p.concepts
    assert p.answer_type == "amount"


def test_language_falls_back_to_dictionary_vote(parse):
    assert parse("Mietkaution").language == "de"
    assert parse("deposit").language == "en"


# -- shape and type


def test_listing_vs_single(parse):
    assert parse("Quels documents faut-il pour l'état des lieux ?").answer_shape == "listing"
    assert parse("What are the steps to register a car?").answer_shape == "listing"
    assert parse("Welche Unterlagen brauche ich für die Anmeldung?").answer_shape == "listing"
    assert parse("Quel est le montant de la garantie locative ?").answer_shape == "single"


@pytest.mark.parametrize(
    "question, answer_type",
    [
        ("Comment se passe l'état des lieux ?", "text"),
        ("Combien coûte le contrôle technique ?", "amount"),
        ("How much is the deposit?", "amount"),
        ("Quand dois-je m'inscrire à la commune ?", "date"),
        ("When is the next technical inspection due?", "date"),
        ("Est-ce que la garantie locative est obligatoire ?", "boolean"),
        ("Can I pay the deposit with a bank guarantee?", "boolean"),
        ("Muss ich mein Auto anmelden?", "boolean"),
        ("Quelle est l'adresse du Biergercenter ?", "address"),
        ("Where is the Biergercenter located?", "address"),
        ("Quel est le numéro de téléphone du contrôle technique ?", "phone"),
        ("Quel est le site web de la commune ?", "url"),
        ("Combien de temps est valable le contrôle technique ?", "duration"),
        ("How long do I have to register with the commune?", "duration"),
    ],
)
def test_each_answer_type(parse, question, answer_type):
    assert parse(question).answer_type == answer_type


def test_boolean_frame_wins_over_a_typed_cue(parse):
    assert parse("Est-ce que je dois payer des frais pour l'immatriculation ?").answer_type == "boolean"


def test_answer_context_follows_shape_and_type(parse):
    assert parse("Quels documents pour l'état des lieux ?").structural_hints.answer_context == "section"
    assert parse("Combien coûte le contrôle technique ?").structural_hints.answer_context == "line"
    assert parse("Comment se passe l'état des lieux ?").structural_hints.answer_context == "paragraph"


# -- keywords


def test_every_keyword_carries_a_source_and_dictionary_keywords_a_concept(parse):
    p = parse("Combien coûte la garantie locative pour un bail ?")
    assert p.keywords
    for k in p.keywords:
        assert k.source in ("direct", "expert_dictionary", "anchor")
        if k.source == "expert_dictionary":
            assert k.concept is not None and 0 < k.weight <= 0.6
        if k.source == "direct":
            assert k.weight == 1.0 and not k.is_regex
        if k.source == "anchor":
            assert k.is_regex and k.weight == 1.0


def test_direct_keywords_are_the_readers_content_words_verbatim(parse):
    p = parse("Combien coûte la garantie locative ?")
    assert [k.text for k in p.keywords if k.source == "direct"] == ["coûte", "garantie", "locative"]


def test_dictionary_keywords_cover_every_language_of_the_concept(parse):
    p = parse("Combien coûte la garantie locative ?")
    expert = {k.text for k in p.keywords if k.concept == "garantie_locative"}
    assert {"caution", "deposit", "mietkaution"} <= expert


def test_anchor_regex_is_added_for_typed_answers(parse):
    amount = [k for k in parse("Combien coûte le contrôle technique ?").keywords if k.source == "anchor"]
    assert len(amount) == 1 and "€" in amount[0].text
    assert not [k for k in parse("Comment se passe l'état des lieux ?").keywords if k.source == "anchor"]


def test_a_number_typed_in_the_question_becomes_an_anchor(parse):
    anchors = [k.text for k in parse("Que veut dire la classe 1 ?").keywords if k.source == "anchor"]
    assert r"\b1\b" in anchors


# -- structural hints


def test_pages_hint_from_the_current_page(parse):
    p = parse("Combien coûte le contrôle technique ?", current_page="voiture")
    assert p.structural_hints.pages_hint == ["voiture"]
    assert parse("Combien coûte le contrôle technique ?").structural_hints.pages_hint is None


def test_pages_hint_phrase_without_a_page_is_noted(parse):
    p = parse("Combien coûte le contrôle technique sur cette page ?")
    assert p.structural_hints.pages_hint is None
    assert any("sur cette page" in n for n in p.parsing_notes)
    assert "page" not in [k.text for k in p.keywords]
    with_page = parse("Combien coûte le contrôle technique sur cette page ?", current_page="voiture")
    assert with_page.structural_hints.pages_hint == ["voiture"]


def test_toc_section_hint_names_the_heading(parse):
    assert parse("Combien coûte la garantie locative ?").structural_hints.toc_section_hint == "Garantie locative"
    assert parse("comment se passe l'etat des lieux").structural_hints.toc_section_hint == "État des lieux"


def test_toc_section_hint_is_fuzzy_and_prefers_the_longest_heading(parse):
    p = parse("immatriculation de mon vehicule")
    assert p.structural_hints.toc_section_hint == "Immatriculation du véhicule"
    assert parse("Combien coûte un vélo ?").structural_hints.toc_section_hint is None


# -- scope and decomposition


def test_topic_from_the_dictionary(parse):
    assert parse("Combien coûte la garantie locative ?").scope_filters.topic == "housing"
    assert parse("Quand dois-je m'inscrire à la commune ?").scope_filters.topic == "administration"
    assert parse("bonjour merci").scope_filters.topic is None


def test_decomposition_by_the_et_and_test(parse):
    p = parse("Comment immatriculer ma voiture et où faire le contrôle technique ?")
    assert p.decomposition.pattern == "independent"
    assert p.decomposition.sub_questions == ["comment immatriculer ma voiture", "où faire le contrôle technique"]
    e = parse("How do I register my car and where is the inspection?")
    assert e.decomposition.pattern == "independent" and len(e.decomposition.sub_questions) == 2


def test_a_coordinated_noun_phrase_is_not_decomposed(parse):
    p = parse("le loyer et les charges")
    assert p.decomposition.pattern == "single" and p.decomposition.sub_questions == []


# -- clarification


def test_too_short(parse):
    p = parse("a")
    assert p.ambiguity_reason == "too_short" and p.suggested_clarification


def test_no_content_words(parse):
    p = parse("comment faire ?")
    assert p.ambiguity_reason == "no_content_words" and p.keywords == []


@pytest.mark.parametrize("question", ["ça ?", "et celui-là ?", "what about it?", "this one?"])
def test_pronoun_only(parse, question):
    assert parse(question).ambiguity_reason == "pronoun_only"


def test_single_term_multiple_concepts_default_from_the_page(parse):
    p = parse("registration", current_page="commune")
    assert p.ambiguity_reason == "single_term_multiple_concepts"
    assert p.candidate_values == ["declaration_arrivee", "immatriculation"]
    assert p.proposed_default == "declaration_arrivee"
    assert p.scope_filters.topic == "administration"
    assert any("proposed_default='declaration_arrivee'" in n and "commune" in n for n in p.parsing_notes)
    assert "declaration of arrival" in p.suggested_clarification


def test_single_term_multiple_concepts_default_from_the_tags(parse, tables):
    p = parse("assurance")
    assert p.ambiguity_reason == "single_term_multiple_concepts"
    assert p.candidate_values == ["assurance_auto", "mutuelle", "responsabilite_civile"]
    assert p.proposed_default == "assurance_auto"  # the only candidate tagged on a page
    assert any("tagged" in n for n in p.parsing_notes)
    assert "assurance auto" in p.suggested_clarification


def test_single_term_of_one_topic_is_not_ambiguous(parse):
    p = parse("loyer")
    assert p.ambiguity_reason is None and p.suggested_clarification is None


def test_default_by_tags_reads_the_index_label_form(parse, dictionary):
    # The fixture tags the commune page "declaration d'arrivee" (brick 1's label), not the concept id.
    assert "declaration d'arrivee" in dictionary.tag_forms("declaration_arrivee")
    p = parse("registration")
    assert p.proposed_default == "declaration_arrivee"  # 1 page each, the tie goes to the name
    assert any("1 page(s)" in n for n in p.parsing_notes)


# -- weak words and words absent from the corpus


def test_weak_words_keep_a_low_weight_and_the_flag(parse):
    p = parse("Comment obtenir les documents pour la garantie locative ?")
    weak = {k.text: k for k in p.keywords if k.weak}
    assert set(weak) == {"obtenir", "documents"}
    assert all(k.weight == 0.3 and k.source == "direct" for k in weak.values())
    strong = [k for k in p.keywords if k.source == "direct" and not k.weak]
    assert [k.text for k in strong] == ["garantie", "locative"] and all(k.weight == 1.0 for k in strong)
    assert p.ambiguity_reason is None


def test_weak_words_alone_have_no_subject(parse):
    p = parse("Comment obtenir des documents ?")
    assert p.ambiguity_reason == "no_content_words"
    assert [k.text for k in p.keywords] == ["obtenir", "documents"]
    assert parse("Where do I get the papers?").ambiguity_reason == "no_content_words"


def test_a_weak_word_does_not_make_a_single_strong_term_ambiguous(parse):
    p = parse("acheter une assurance")
    assert p.ambiguity_reason == "single_term_multiple_concepts"  # "assurance" is the only strong word


def test_unknown_words_stay_keywords_with_in_corpus_false(parse):
    p = parse("Où acheter un sapin de noël ?")
    by_text = {k.text: k for k in p.keywords if k.source == "direct"}
    assert by_text["sapin"].weight == 1.0 and by_text["sapin"].in_corpus is False
    assert by_text["noël"].in_corpus is False
    assert any("sapin" in n and "in_corpus=false" in n for n in p.parsing_notes)
    known = {k.text: k for k in parse("Combien coûte la garantie locative ?").keywords}
    assert known["garantie"].in_corpus is True and known["mietkaution"].in_corpus is False


def test_clarification_is_written_in_the_question_language(parse):
    assert "too short" in parse("a").suggested_clarification or "trop courte" in parse("a").suggested_clarification
    assert "Thema des Leitfadens" in parse("wie geht das?").suggested_clarification  # pronoun_only, in German
    assert "subject of the guide" in parse("how do I do this?").suggested_clarification


# -- determinism


def test_same_input_gives_identical_json(parse):
    q = "Combien coûte la garantie locative et quand dois-je m'inscrire à la commune ?"
    first = parse(q, current_page="logement").model_dump_json()
    second = parse(q, current_page="logement").model_dump_json()
    assert first == second


def test_parsed_question_round_trips_through_json(parse):
    p = parse("Quels documents pour l'inscription à la commune ?", current_page="commune")
    assert ParsedQuestion.model_validate_json(p.model_dump_json()) == p


# -- from the evaluation over the real corpus


def test_home_insurance_phrase_reaches_assurance_habitation(parse):
    p = parse("quelles garanties couvre l'assurance habitation ?")
    assert p.concepts[0] == "assurance_habitation" and p.answer_shape == "listing"
    assert p.scope_filters.topic == "housing"  # the index files "Assurer son logement" there
    assert "logement" in parse("une habitation à louer").concepts  # the bare word reaches housing


def test_german_separable_verb_reaches_declaration_arrivee(parse):
    for q in ["wie melde ich mich bei der Gemeinde an?", "Anmeldung bei der Gemeinde", "wo kann ich mich anmelden?"]:
        p = parse(q)
        assert "declaration_arrivee" in p.concepts, q
        assert p.language == "de"
        assert "mich" not in [k.text for k in p.keywords]


def test_pronoun_with_only_weak_words_is_pronoun_only(parse):
    p = parse("ça marche comment ?")
    assert p.ambiguity_reason == "pronoun_only"
    assert [k.text for k in p.keywords if k.weak] == ["marche"]
    assert parse("how does it work?").ambiguity_reason == "pronoun_only"
    assert parse("comment ça fonctionne ?").ambiguity_reason == "pronoun_only"


def test_luxembourg_is_a_weak_word_in_every_language(parse):
    for q in ["un bail au Luxembourg", "a lease in Luxembourg", "ein Mietvertrag in Luxemburg"]:
        lux = [k for k in parse(q).keywords if k.text.lower().startswith("luxem")]
        assert lux and lux[0].weak and lux[0].weight == 0.3, q
