"""The arbiter's rules, one test per rule, on hand-built briefs."""

from test_retrieval_fixtures import DICTIONARY  # noqa: F401  (sets sys.path first)

from guide_rag.retrieval.arbiter import CandidateBrief, decide, title_concepts


def brief(cid, title, keywords, concepts, *, title_keywords=(), co=None, score=1.0, required=None, has=False,
          coverage=1.0, covered=None, uncovered=(), strong=True, title_cov=0.0, doc_cov=0.0, doc_title=""):
    return CandidateBrief(candidate_id=cid, doc_id=cid.split("#")[0], section_id=None, section_title=title,
                          matched_keywords=list(keywords), matched_concepts=list(concepts), title_keywords=list(title_keywords),
                          co_occurrence=co, required_anchor=required, has_required_anchor=has, score=score,
                          coverage=coverage, covered=list(covered if covered is not None else keywords), uncovered=list(uncovered),
                          strong_covered=strong, title_coverage=title_cov, doc_title_coverage=doc_cov, doc_title=doc_title)


Q = ["bail", "loyer"]


def test_title_plus_co_occurrence_is_primary():
    d = decide([brief("logement#l4-l5", "Bail", ["bail", "loyer"], ["bail", "loyer"], title_keywords=["bail"], co="line", score=3.0, title_cov=0.5)], Q, DICTIONARY)
    assert d["logement#l4-l5"].role == "primary"
    assert d["logement#l4-l5"].reason == "The section 'Bail' title names 'bail' and 'loyer' (coverage 1.00); score 3.0: primary."


def test_co_occurrence_alone_primary_or_supporting_by_score():
    d = decide([
        brief("a#l1-l1", "Intro", ["bail", "loyer"], ["bail", "loyer"], co="section", score=3.0),
        brief("b#l1-l1", "Intro", ["bail", "loyer"], ["bail", "loyer"], co="section", score=1.0),
    ], Q, DICTIONARY)
    assert d["a#l1-l1"].role == "primary" and "is the highest" in d["a#l1-l1"].reason
    assert d["b#l1-l1"].role == "supporting" and "behind a#l1-l1" in d["b#l1-l1"].reason


def test_single_keyword_is_tangential():
    d = decide([brief("a#l1-l1", "Intro", ["bail"], ["bail"], score=1.0, coverage=0.5), brief("b#l2-l2", "Intro", ["bail", "loyer"], ["bail", "loyer"], co="line", score=3.0)], Q, DICTIONARY, n_strong_present=2)
    assert d["a#l1-l1"].role == "tangential"
    assert d["a#l1-l1"].reason == "Only 'bail' hits these lines: no second concept and no title match."


def test_section_naming_another_concept_is_discarded():
    d = decide([brief("logement#l11-l11", "Garantie locative", ["bail"], ["bail"], score=1.0)], ["bail"], DICTIONARY)
    assert d["logement#l11-l11"].role == "discarded"
    assert d["logement#l11-l11"].reason == "The section 'Garantie locative' names 'garantie locative', not 'bail'; its lines carry only 'bail'."


def test_foreign_title_with_co_occurrence_is_not_discarded():
    d = decide([brief("logement#l10-l10", "Garantie locative", ["bail", "loyer"], ["bail", "loyer"], co="line", score=3.0)], Q, DICTIONARY)
    assert d["logement#l10-l10"].role == "primary"


def test_required_anchor_ranks_first_among_equals_and_is_reported_missing_otherwise():
    d = decide([
        brief("a#l1-l1", "Intro", ["bail", "loyer"], ["bail", "loyer"], co="line", score=3.0, required="amount", has=False),
        brief("c#l1-l1", "Intro", ["bail", "loyer"], ["bail", "loyer"], co="line", score=2.0, required="amount", has=True),
    ], Q, DICTIONARY, answer_type="amount")
    assert d["c#l1-l1"].role == "primary"
    assert d["a#l1-l1"].role == "supporting" and "carries no amount, which an answer of type amount requires and c#l1-l1 has" in d["a#l1-l1"].reason
    alone = decide([brief("a#l1-l1", "Bail", ["bail", "loyer"], ["bail", "loyer"], title_keywords=["bail"], co="line", score=3.0, required="amount", has=False, title_cov=0.5)],
                   Q, DICTIONARY, answer_type="amount")
    assert alone["a#l1-l1"].role == "primary" and alone["a#l1-l1"].reason.endswith("(no amount on the lines: the typed value is missing).")


def test_one_strong_word_present_makes_the_best_hit_primary():
    d = decide([brief("v#l4-l5", "Immatriculation", ["immatriculation"], ["immatriculation"], title_keywords=["immatriculation"], score=2.0,
                      coverage=0.77, covered=["immatriculation"], uncovered=["documents"], title_cov=0.77)],
               ["documents", "immatriculation"], DICTIONARY, n_strong_present=1)
    assert d["v#l4-l5"].role == "primary"
    assert d["v#l4-l5"].reason == "The section 'Immatriculation' title names 'immatriculation' (coverage 0.77); score 2.0: primary."


def test_coverage_below_the_threshold_never_makes_a_primary():
    d = decide([
        brief("achat#l1-l1", "Acheter un logement", ["acheter"], ["acheter"], title_keywords=["acheter"], score=2.0,
              coverage=0.13, covered=["acheter"], uncovered=["sapin", "noël"], strong=False, title_cov=0.13),
        brief("bail#l9-l9", "Interdictions", ["acheter"], ["acheter"], score=1.0, coverage=0.13, covered=["acheter"], uncovered=["sapin", "noël"], strong=False),
    ], ["acheter", "sapin", "noel"], DICTIONARY)
    assert d["achat#l1-l1"].role == "supporting"
    assert d["achat#l1-l1"].reason == "Covers only generic words (0.13 of the question's words); 'sapin' and 'noël' not covered: supporting."
    assert d["bail#l9-l9"].role == "tangential"
    d2 = decide([brief("x#l1-l1", "Intro", ["voiture"], ["voiture"], co="line", score=3.0, coverage=0.33, covered=["voiture"], uncovered=["sapin", "noel"])], ["voiture", "sapin", "noel"], DICTIONARY)
    assert d2["x#l1-l1"].role == "supporting" and "Covers only 'voiture' (0.33" in d2["x#l1-l1"].reason


def test_trust_the_toc_document_and_section_titles_win_over_a_line_hit():
    d = decide([
        brief("faq#l17-l18", "Dans quel délai immatriculer un véhicule ?", ["immatriculer", "véhicule"], ["immatriculation", "voiture"],
              title_keywords=["immatriculer", "véhicule"], co="line", score=6.4, title_cov=1.0, doc_cov=0.0, doc_title="Questions et réponses"),
        brief("vehicule#l4-l5", "Immatriculer son véhicule", ["plaques"], ["immatriculation"], title_keywords=["immatriculer"], co="section",
              score=3.0, title_cov=1.0, doc_cov=1.0, doc_title="Immatriculer son véhicule"),
        brief("vehicule#l129-l129", "Rouler avant l'immatriculation", ["immatriculation", "véhicule"], ["immatriculation", "voiture"],
              title_keywords=["immatriculation"], co="line", score=3.2, title_cov=0.5, doc_cov=1.0, doc_title="Immatriculer son véhicule"),
    ], ["immatriculation", "voiture"], DICTIONARY)
    assert d["vehicule#l4-l5"].role == "primary"
    assert d["vehicule#l4-l5"].reason.startswith("The document 'Immatriculer son véhicule' and the section 'Immatriculer son véhicule' name the question's words")
    assert d["faq#l17-l18"].role == "supporting" and d["faq#l17-l18"].reason.endswith("is titled with the question's words: supporting (also answered here).")
    assert d["vehicule#l129-l129"].role == "supporting"


def test_coverage_outranks_a_partial_title_match():
    d = decide([
        brief("fiches#l15-l15", "Choisir sa commune", ["commune"], ["commune"], title_keywords=["commune"], score=2.0, coverage=0.43, covered=["commune"], uncovered=["inscrire"], title_cov=0.43),
        brief("arrivee#l2-l4", "Les huit premiers jours", ["commune", "arrivée"], ["commune", "declaration_arrivee"], co="line", score=3.3, coverage=1.0, covered=["inscrire", "commune"]),
    ], ["inscrire", "commune"], DICTIONARY)
    assert d["arrivee#l2-l4"].role == "primary" and d["fiches#l15-l15"].role == "supporting"
    assert "covers more of the question (1.00)" in d["fiches#l15-l15"].reason


def test_title_concepts_reads_the_dictionary():
    assert title_concepts("Garantie locative", DICTIONARY) == ["garantie_locative"]
    assert title_concepts("Contrôle technique", DICTIONARY) == ["controle_technique"]
    assert title_concepts("Introduction", DICTIONARY) == []
