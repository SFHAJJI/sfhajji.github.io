"""The rules added by the quality pass on the real index: hyphenated compounds, weak words, the
coverage rule, concept assignment of direct words, title tiers, the pointer rule, the procedure and
yes/no contexts, counts as amounts, the partial-answer cap. A JS port mirrors each of them."""

import pandas as pd
from test_retrieval_fixtures import DICTIONARY, expand, kw, make_tables, plan_for, pq, q_bail, q_garantie

from guide_rag.generation.pipeline import answer_question
from guide_rag.generation.verbatim import generate_verbatim
from guide_rag.retrieval.contracts import (Keyword, ambiguous_variants, concept_words, content_words, coverage, question_terms,
                                           title_exact)
from guide_rag.retrieval.detectors import find_anchors, number_word_value
from guide_rag.retrieval.result import answer_context_for, retrieve
from guide_rag.retrieval.text import contains_keyword, is_procedure_question, is_weak, stems, tokens, variant_regex


# --- topic tier and the foreign title on an off-topic page ---------------------------------------


def test_topic_tier_ranks_the_pages_of_the_questions_topic_first():
    from guide_rag.retrieval.arbiter import CandidateBrief, decide

    def brief(cid, title, topic, cov=1.0):
        return CandidateBrief(candidate_id=cid, doc_id=cid.split("#")[0], section_id=None, section_title=title, matched_keywords=["garantie", "couvre"],
                              matched_concepts=["assurance_habitation"], co_occurrence="line", coverage=cov, covered=["garanties", "couvre"],
                              strong_covered=True, page_topic=topic, score=2.0)

    pair = lambda: [brief("comparateur#l16-l16", "Pourquoi comparer", "other", cov=1.0), brief("assurance_habitation#l5-l5", "Ce que couvre un contrat", "housing", cov=0.75)]
    d = decide(pair(), ["assurance_habitation"], DICTIONARY, question_topic="housing")
    assert d["assurance_habitation#l5-l5"].role == "primary"
    assert d["comparateur#l16-l16"].role == "supporting" and "topic 'other' is not the question's 'housing'" in d["comparateur#l16-l16"].reason
    d2 = decide(pair(), ["assurance_habitation"], DICTIONARY)  # without a scope topic, coverage decides
    assert d2["comparateur#l16-l16"].role == "primary"


def test_foreign_title_on_an_off_topic_page_is_discarded_when_a_page_of_the_topic_answers():
    t = make_tables()
    t.line_df.loc[len(t.line_df)] = {"doc_id": "voiture", "line_num": 12, "text": "Le bail et le loyer n'ont rien à voir avec le contrôle technique.",
                                     "element": "p", "section_id": "voiture#s3", "anchor_id": "ct", "css_path": "p", "char_count": 60, "is_heading": False}
    t.toc_df.loc[t.toc_df.section_id.isin(["voiture#s1", "voiture#s3"]), "end_line"] = 12
    idx = t.corpus_index.index[t.corpus_index.doc_id == "voiture"][0]  # level 0 must keep the page: give its summary the terms
    t.corpus_index.at[idx, "tags"] = ["voiture", "bail", "loyer"]
    t.corpus_index.at[idx, "summary_line"] = "Voiture — démarches. Bail, loyer, contrôle technique."
    q = pq("quel loyer dans le bail", [kw("loyer", concept="loyer"), kw("bail", concept="bail")], scope_filters={"topic": "housing"})
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert r.primaries[0].anchor.doc_id == "logement" and r.primaries[0].topic_match
    foreign = next(c for c in r.candidates if c.candidate_id == "voiture#l12-l12")
    assert foreign.role == "discarded" and foreign.co_occurrence == "line"
    assert foreign.reason.startswith("The section 'Contrôle technique' names 'controle technique', not 'loyer / bail': its page's topic 'vehicle' is not the question's 'housing'")
    q2 = pq("quel loyer dans le bail", [kw("loyer", concept="loyer"), kw("bail", concept="bail")])  # no scope topic: the line stays eligible
    assert next(c for c in retrieve(q2, plan_for(q2), t, DICTIONARY).candidates if c.candidate_id == "voiture#l12-l12").role != "discarded"


# --- text -----------------------------------------------------------------------------------


def test_hyphenated_compounds_are_one_token():
    assert tokens("Belgique, Car-Pass") == ["belgique", "car-pass"]
    assert not contains_keyword("Belgique, Car-Pass", "car")  # a bare word never matches inside a compound
    assert contains_keyword("Belgique, Car-Pass", "car-pass")
    assert contains_keyword("prendre rendez-vous en ligne", "rendez vous")  # a phrase meets the compound
    assert not variant_regex("car").search("belgique, car-pass") and variant_regex("car").search("une car ancienne")


def test_weak_words_come_from_brick_2s_asset():
    assert is_weak("documents") and is_weak("acheter") and is_weak("Documents à fournir") is False
    assert not is_weak("immatriculation")
    terms = question_terms(pq("où acheter un sapin", [kw("acheter"), kw("sapin")]), DICTIONARY)
    assert [(t.text, t.weight, t.weak) for t in terms] == [("acheter", 0.3, True), ("sapin", 1.0, False)]
    flagged = question_terms(pq("x", [Keyword(text="truc", weight=0.3, source="direct", weak=True)]), DICTIONARY)
    assert flagged[0].weak and flagged[0].weight == 0.3


def test_procedure_cues():
    assert is_procedure_question("comment immatriculer ma voiture") and is_procedure_question("How do I register my car")
    assert not is_procedure_question("combien coûte l'immatriculation")


# --- content words and coverage ---------------------------------------------------------------


def test_direct_words_take_a_concept_through_a_phrase_variant_but_not_an_ambiguous_one():
    d = dict(DICTIONARY, responsabilite_civile=["responsabilité civile", "assurance"], assurance_auto=["assurance auto", "assurance"])
    q = pq("assurance responsabilité civile obligatoire", [kw("assurance"), kw("responsabilité"), kw("civile"), kw("obligatoire"),
                                                            kw("responsabilité civile", 0.6, "expert_dictionary", "responsabilite_civile")])
    terms = {t.text: t for t in question_terms(q, d)}
    assert ambiguous_variants(d) == {"assurance"}
    assert terms["responsabilité"].concept == "responsabilite_civile" and terms["civile"].concept == "responsabilite_civile"
    assert terms["assurance"].concept is None and terms["obligatoire"].concept is None
    words = content_words(list(terms.values()), d)
    # "assurance" alone never proves responsabilite_civile: the title covers only the word "assurance".
    cov, covered, uncovered = coverage(words, [stems("Primes d'assurance et intérêts débiteurs")])
    assert (cov, covered) == (0.25, ["assurance"])


def test_coverage_counts_weights_and_in_corpus():
    q = pq("how many days of annual leave", [kw("days"), Keyword(text="leave", in_corpus=False), Keyword(text="sapin", in_corpus=False), *expand("bail")])
    d = dict(DICTIONARY, conge=["congé", "leave"])
    terms = question_terms(q, d)
    words = content_words(terms, d)
    cov, covered, uncovered = coverage(words, [stems("vingt-six jours (26 days) de congé")])
    assert covered == ["days", "leave"] and uncovered == ["sapin"]  # "leave" is covered through "congé"; "sapin" never
    assert cov == round(sum(w.weight for w in words if w.text in covered) / sum(w.weight for w in words), 3)
    assert coverage(words, [stems("vingt-six jours de congé")])[1] == ["leave"]  # "days" has no concept: only itself counts
    assert [w.text for w in concept_words(words)] == ["leave"]  # the strong word that carries a concept


def test_words_not_covered_gives_not_found_and_lists_them():
    q = pq("sapin noël voiture", [Keyword(text="sapin", in_corpus=False), Keyword(text="noël", in_corpus=False), kw("voiture", concept="voiture")])
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.not_found and r.not_found_reason.startswith("words_not_covered: sapin, noël")
    assert r.uncovered_words == ["sapin", "noël"] and all(c.role in ("supporting", "tangential") for c in r.candidates)
    g = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert g.answer.kind == "absence" and g.answer.reason == "concept_not_found"
    assert [(c.concept, c.line_hits) for c in g.answer.searched_concepts][:2] == [("sapin", 0), ("noel", 0)]


def test_generic_words_alone_never_anchor_a_primary():
    q = pq("prendre rendez-vous", [kw("prendre"), kw("rendez-vous")])  # "prendre" is weak, "rendez-vous" hits line 10 of voiture
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.primaries and r.primaries[0].candidate_id == "voiture#l10-l10"
    q2 = pq("prendre", [kw("prendre")])
    r2 = retrieve(q2, plan_for(q2), make_tables(), DICTIONARY)
    assert r2.not_found


# --- titles, tiers and the pointer rule -------------------------------------------------------


def _with_faq(t):
    """A FAQ page whose answer points to the logement fiche, as the real corpus does ("Voir la fiche")."""
    rows = [
        {"doc_id": "faq", "line_num": 1, "text": "Questions et réponses", "element": "h1", "section_id": "faq#s1", "anchor_id": "top", "css_path": "h1", "char_count": 21, "is_heading": True},
        {"doc_id": "faq", "line_num": 2, "text": "Combien coûte la garantie locative ?", "element": "h3", "section_id": "faq#s2", "anchor_id": "q1", "css_path": "h3", "char_count": 36, "is_heading": True},
        {"doc_id": "faq", "line_num": 3, "text": "Deux mois de loyer au plus, soit 1 500 € pour un loyer de 750 €.", "element": "p", "section_id": "faq#s2", "anchor_id": "q1", "css_path": "p", "char_count": 60, "is_heading": False},
        {"doc_id": "faq", "line_num": 4, "text": "Voir la fiche : Logement", "element": "p", "section_id": "faq#s2", "anchor_id": "q1", "css_path": "p", "char_count": 24, "is_heading": False},
    ]
    t.line_df = pd.concat([t.line_df, pd.DataFrame(rows)], ignore_index=True)
    t.toc_df = pd.concat([t.toc_df, pd.DataFrame([
        {"doc_id": "faq", "section_id": "faq#s1", "level": 1, "parent_id": None, "title": "Questions et réponses", "breadcrumb": "Questions et réponses", "start_line": 1, "end_line": 4, "anchor_id": "top", "source": "headings"},
        {"doc_id": "faq", "section_id": "faq#s2", "level": 3, "parent_id": "faq#s1", "title": "Combien coûte la garantie locative ?", "breadcrumb": "Questions et réponses › Combien coûte la garantie locative ?", "start_line": 2, "end_line": 4, "anchor_id": "q1", "source": "headings"},
    ])], ignore_index=True)
    t.corpus_index = pd.concat([t.corpus_index, pd.DataFrame([{
        "doc_id": "faq", "url": "https://example.org/faq", "title": "Questions et réponses", "topic": "other",
        "summary_line": "Questions et réponses.", "tags": [], "n_lines": 4, "lang": "fr"}])], ignore_index=True)
    t.cross_ref_df = pd.DataFrame([{"doc_id": "faq", "line_num": 4, "target_doc_id": "logement", "target_anchor": "garantie", "context": "Voir la fiche : Logement"}])
    return t


def test_pointer_rule_defers_the_faq_to_the_fiche_it_links():
    t = _with_faq(make_tables())
    q = q_garantie()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert r.primaries[0].candidate_id == "logement#l9-l10"
    # The FAQ's h3 names the question; its answer line carries the amount: one candidate l2-l3.
    faq = next(c for c in r.candidates if c.candidate_id == "faq#l2-l3")
    assert faq.role == "supporting" and "points to 'Logement' (Voir la fiche)" in faq.reason and faq.reason.endswith("(also answered here).")


def test_without_the_link_the_faq_title_match_ties_and_the_router_decides():
    t = _with_faq(make_tables())
    t.cross_ref_df = None
    t.line_df.loc[(t.line_df.doc_id == "faq") & (t.line_df.line_num == 2), "text"] = "Garantie locative"
    t.toc_df.loc[t.toc_df.section_id == "faq#s2", "title"] = "Garantie locative"
    q = q_garantie()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    # Both titles are exactly the question's concept, both cover it fully and carry the amount: the
    # tiers tie, the section-title coverage ties, and the router's page tally breaks the tie.
    roles = {c.candidate_id: c.role for c in r.candidates}
    assert roles["logement#l9-l10"] == "primary" and roles["faq#l2-l3"] == "supporting"
    assert "the router ranks the page of logement#l9-l10 first" in next(c.reason for c in r.candidates if c.candidate_id == "faq#l2-l3")


def test_document_title_outranks_a_section_title_elsewhere_at_equal_coverage():
    t = make_tables()
    t.line_df.loc[len(t.line_df)] = {"doc_id": "logement", "line_num": 17, "text": "Le contrôle technique de la voiture n'a rien à voir avec le bail.",
                                     "element": "p", "section_id": "logement#s4", "anchor_id": "edl", "css_path": "p", "char_count": 60, "is_heading": False}
    t.toc_df.loc[t.toc_df.section_id == "logement#s4", "end_line"] = 17
    t.toc_df.loc[t.toc_df.section_id == "logement#s1", "end_line"] = 17
    q = pq("comment passer le contrôle technique de la voiture", [kw("passer"), kw("contrôle technique", concept="controle_technique"), kw("voiture", concept="voiture"), *expand("controle_technique")])
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert r.primaries[0].anchor.doc_id == "voiture" and r.primaries[0].title_tier >= 2
    assert r.answer_context_used == "section"  # a "comment" question reads the section's steps


def test_exact_title_match_comes_first():
    typed = content_words(question_terms(pq("montant de la garantie locative", [kw("montant"), kw("garantie locative", concept="garantie_locative")]), DICTIONARY), DICTIONARY)
    assert title_exact("Garantie locative", typed) and not title_exact("La garantie bancaire, un piège", typed)
    assert not title_exact("", typed)
    # Only the reader's own words count: with "garantie" typed alone, "Garantie locative" is not exact.
    assert not title_exact("Garantie locative", content_words(question_terms(q_garantie(), DICTIONARY), DICTIONARY))
    # "Étapes" (a weak word) is exactly in "quelles sont les étapes pour…"; a FAQ heading with words of its own is not.
    q = pq("quelles sont les étapes pour l'immatriculation", [kw("étapes"), kw("immatriculation", concept="immatriculation")], answer_shape="listing")
    w = content_words(question_terms(q, DICTIONARY), DICTIONARY)
    assert title_exact("Étapes", w) and title_exact("Immatriculation", w) and not title_exact("Dans quel délai immatriculer un véhicule ?", w)
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.primaries[0].title_exact and r.primaries[0].section_title == "Immatriculation"
    assert "is exactly in the question" in r.primaries[0].reason


def test_title_tier_counts_concept_words_only():
    # "moins" and "cher" are strong but carry no concept: a title made of them earns no tier.
    q = pq("comment obtenir luxtrust moins cher", [kw("obtenir"), kw("luxtrust"), kw("moins"), kw("cher")])
    assert [w.text for w in concept_words(content_words(question_terms(q, DICTIONARY), DICTIONARY))] == ["luxtrust", "moins", "cher"]
    q2 = pq("comment obtenir le bail moins cher", [kw("obtenir"), kw("bail", concept="bail"), kw("moins"), kw("cher")])
    assert [w.text for w in concept_words(content_words(question_terms(q2, DICTIONARY), DICTIONARY))] == ["bail"]


# --- contexts, amounts, generation ------------------------------------------------------------


def test_procedure_and_yes_no_contexts():
    q = pq("comment obtenir la garantie locative", [kw("obtenir"), kw("garantie locative", concept="garantie_locative")])
    assert answer_context_for(q)[0] == "section"
    b = pq("est-ce que la garantie locative est rendue", [kw("garantie locative", concept="garantie_locative"), kw("rendue")], answer_type="boolean")
    assert answer_context_for(b)[0] == "paragraph"
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    p = r.primaries[0]
    assert (p.context.line_start, p.context.line_end) == (8, 11)  # the section's own lines
    a = generate_verbatim(q, r, make_tables())
    assert a.items[0].spans[0].line_start == 9 and a.items[0].spans[0].line_end == 11  # the heading line is left out
    assert a.complete_answer_found


def test_boolean_quotes_the_sentence_that_answers():
    q = pq("est-ce que la garantie locative est rendue à la fin du bail", [kw("garantie locative", concept="garantie_locative"), kw("rendue"), kw("bail", concept="bail")], answer_type="boolean")
    a = generate_verbatim(q, retrieve(q, plan_for(q), make_tables(), DICTIONARY), make_tables())
    assert a.items[0].boolean is True
    assert a.items[0].spans[0].quote == "Elle est rendue à la fin du bail après l'état des lieux de sortie."


def test_counts_are_amounts_and_number_words_compound():
    assert number_word_value("vingt-six") == 26 and number_word_value("quatre-vingt-dix") == 90 and number_word_value("soixante et un") == 61
    caps = find_anchors("Le congé annuel légal s'élève à vingt-six jours ouvrables par an.", "amount")
    assert [(c["value"], c["unit"]) for c in caps] == [(26.0, "jours ouvrables")]
    caps = find_anchors("Elle correspond à deux mois de loyer, soit 1 500 €.", "amount")
    assert [c["raw"] for c in caps] == ["deux mois de loyer", "1 500 €"]  # no duplicate "deux mois"


def test_partial_answers_are_capped_at_0_6():
    q = pq("Qu'est-ce que le bail ?", [kw("bail", concept="bail")], answer_context="line")
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    a = generate_verbatim(q, r, make_tables())
    assert r.confidence > 0.6 and not a.complete_answer_found and a.confidence == 0.6
    full = generate_verbatim(q_bail(), retrieve(q_bail(), plan_for(q_bail()), make_tables(), DICTIONARY), make_tables())
    assert full.complete_answer_found and full.confidence > 0.6


def test_missing_typed_value_keeps_the_best_section_primary():
    q = pq("quel est le délai de l'état des lieux", [kw("délai"), kw("état des lieux", concept="etat_des_lieux"), *expand("etat_des_lieux")], answer_type="duration")
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    p = r.primaries[0]
    assert p.anchor.section_id == "logement#s4" and "the typed value is missing" in p.reason
