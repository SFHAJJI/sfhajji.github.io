"""The two-level router of SPEC §2b: pages with a reason each, then the outline descent."""

from test_retrieval_fixtures import DICTIONARY, kw, make_tables, plan_for, pq, q_bail, q_garantie, q_immat_list, q_permis

from guide_rag.retrieval.contracts import concept_variants, question_terms
from guide_rag.retrieval.detectors import keyword_lines, line_records
from guide_rag.retrieval.router import route, route_level0, route_level1


def terms_of(parsed):
    return question_terms(parsed, concept_variants(DICTIONARY, parsed))


def test_level0_keeps_the_right_page_with_a_reason():
    kept, scores = route_level0(q_garantie(), make_tables(), terms_of(q_garantie()))
    assert [p.doc_id for p in kept] == ["logement"]
    assert kept[0].reason.startswith("kept: ") and "summary line" in kept[0].reason
    assert "heading title match (Garantie locative)" in kept[0].reason and "concept(s) in tags" in kept[0].reason
    assert "tally" in kept[0].reason and "voiture" not in scores


def test_level0_boosts_the_readers_page():
    q = q_bail(pages_hint=["logement"])
    kept, _ = route_level0(q, make_tables(), terms_of(q))
    assert kept[0].doc_id == "logement" and "the reader's page x1.3" in kept[0].reason and kept[0].score == 3.9


def test_level0_readers_page_without_terms_does_not_outrank_a_real_hit():
    q = q_garantie(pages_hint=["voiture"])
    kept, scores = route_level0(q, make_tables(), terms_of(q))
    assert [p.doc_id for p in kept] == ["logement"] and scores["voiture"] == 0.5


def test_level0_keeps_nothing_when_no_term_matches():
    kept, scores = route_level0(q_permis(), make_tables(), terms_of(q_permis()))
    assert kept == [] and scores == {}


def test_level1_stops_at_a_leaf_with_a_reason():
    t = make_tables()
    q = q_garantie()
    hits = keyword_lines(line_records(t.line_df, ["logement"]), terms_of(q))
    secs = route_level1(q, t, "logement", terms_of(q), hits)
    assert [s.section_id for s in secs] == ["logement#s3"]
    assert "title 'Garantie locative' matches" in secs[0].reason and secs[0].reason.endswith("a leaf, stop here")


def test_level1_descends_past_a_small_root_to_the_titled_child():
    t = make_tables()
    q = q_immat_list()
    hits = keyword_lines(line_records(t.line_df, ["voiture"]), terms_of(q))
    secs = route_level1(q, t, "voiture", terms_of(q), hits)
    assert [s.section_id for s in secs] == ["voiture#s2"]


def test_level1_follows_the_toc_section_hint():
    t = make_tables()
    q = pq("Et la voiture ?", [kw("voiture", concept="voiture")], toc_hint="Contrôle technique")
    hits = keyword_lines(line_records(t.line_df, ["voiture"]), terms_of(q))
    secs = route_level1(q, t, "voiture", terms_of(q), hits)
    assert secs[0].section_id == "voiture#s3" and "hint:Contrôle technique" in secs[0].matched_terms


def test_route_with_toc_off_reads_the_page_whole():
    q = q_garantie()
    r = route(q, plan_for(q, use_toc=False), make_tables(), terms_of(q))
    assert [p.doc_id for p in r.pages] == ["logement"] and r.sections == []
    assert any("use_toc is off" in n for n in r.notes)
