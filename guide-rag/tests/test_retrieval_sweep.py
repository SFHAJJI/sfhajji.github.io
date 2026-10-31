"""The absence sweep is exhaustive: every page, every line, every variant; not top-k."""

from test_retrieval_fixtures import DICTIONARY, expand, kw, make_tables, pq, q_garantie, q_permis

from guide_rag.retrieval.sweep import question_concept_variants, sweep
from guide_rag.retrieval.text import fold, variant_regex


def test_sweep_covers_every_page_and_line():
    t = make_tables()
    s = sweep(q_garantie(), t, DICTIONARY)
    assert s.pages_scanned == 2 and s.lines_scanned == 27
    # Every line of every page that carries any variant is a row, whatever the router kept.
    # The variants are the dictionary's plus the question's own keyword "garantie".
    expected = set()
    for r in t.line_df.to_dict("records"):
        for v in DICTIONARY["garantie_locative"] + ["garantie"]:
            if variant_regex(v).search(fold(r["text"])):
                expected.add((r["doc_id"], r["line_num"], v))
    assert {(r.doc_id, r.line_num, r.variant) for r in s.rows} == expected
    assert ("logement", 8, "garantie") in expected and ("logement", 9, "garantie locative") in expected
    assert s.concepts[0].pages_with_hits == ["logement"] and s.concepts[0].line_hits == len(expected)


def test_zero_rows_for_an_absent_concept():
    s = sweep(q_permis(), make_tables(), DICTIONARY)
    assert {c.concept: c.line_hits for c in s.concepts} == {"echanger": 0, "permis": 0}
    assert s.rows == []
    assert s.concepts[1].variants == ["permis de conduire", "driving licence", "permis"]


def test_sweep_uses_every_variant_including_other_languages():
    t = make_tables()
    t.line_df.loc[len(t.line_df)] = {"doc_id": "voiture", "line_num": 12, "text": "The car registration is done at the administration.",
                                     "element": "p", "section_id": "voiture#s3", "anchor_id": "ct", "css_path": "p", "char_count": 10, "is_heading": False}
    q = pq("registration?", [kw("registration", concept="immatriculation"), *expand("immatriculation")], language="en")
    s = sweep(q, t, DICTIONARY)
    assert ("voiture", 12, "registration") in {(r.doc_id, r.line_num, r.variant) for r in s.rows}


def test_sweep_sweeps_pages_the_router_never_kept():
    # "loyer" lives on logement only; the question also names a car term, so both pages carry a hit.
    q = pq("loyer voiture", [kw("loyer", concept="loyer"), kw("voiture", concept="voiture")])
    s = sweep(q, make_tables(), DICTIONARY)
    assert {c.concept: c.pages_with_hits for c in s.concepts} == {"loyer": ["logement"], "voiture": ["voiture"]}


def test_question_concept_variants_merges_dictionary_and_question():
    q = pq("x", [kw("caution", concept="garantie_locative"), kw("signé")])
    assert question_concept_variants(q, DICTIONARY) == {
        "garantie_locative": ["garantie locative", "caution", "deposit", "rental guarantee"],
        "signe": ["signé"],
    }
