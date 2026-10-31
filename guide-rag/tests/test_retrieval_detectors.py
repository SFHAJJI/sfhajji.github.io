"""Each detector of SPEC §3 on the synthetic guide."""

from test_retrieval_fixtures import DICTIONARY, make_tables  # noqa: F401  (sets sys.path first)

from guide_rag.retrieval.contracts import Term
from guide_rag.retrieval.detectors import (anchor_regex, co_occurrence, current_page_boost, find_anchors, keyword_lines,
                                           line_records, required_anchor_kind, row_match, title_match)
from guide_rag.retrieval.text import contains_keyword, fold, stem


def term(text, weight=1.0, concept=None, is_regex=False):
    return Term(text=text, weight=weight, source="direct", concept=concept, is_regex=is_regex, concept_key=concept or fold(text))


def test_keyword_lines_whole_word_only():
    lines = line_records(make_tables().line_df)
    hits = keyword_lines(lines, [term("bail")])
    assert {(h.doc_id, h.line_num) for h in hits} == {("logement", 3), ("logement", 4), ("logement", 5), ("logement", 6), ("logement", 11)}
    # "bail" must not hit inside another word.
    assert not contains_keyword("Le bailleur paie", "bail")


def test_keyword_lines_accent_folded_and_stemmed():
    lines = line_records(make_tables().line_df)
    assert {h.line_num for h in keyword_lines(lines, [term("etat des lieux")])} == {11, 12, 13}
    assert {h.line_num for h in keyword_lines(lines, [term("garanties")])} == {8, 9}
    assert stem("garanties") == stem("garantie") and stem("locatives") == stem("locative")


def test_keyword_lines_regex_term_searches_raw_text():
    lines = line_records(make_tables().line_df)
    hits = keyword_lines(lines, [term(r"\d+ ?€", is_regex=True)])
    assert {(h.doc_id, h.line_num) for h in hits} == {("logement", 7), ("logement", 10), ("voiture", 5)}


def test_title_match_on_toc():
    hits = title_match(make_tables().toc_df, [term("garantie"), term("contrôle technique")])
    assert [(h.section_id, h.keyword) for h in hits] == [("logement#s3", "garantie"), ("voiture#s3", "contrôle technique")]


def test_anchor_amount_euro_and_words():
    caps = find_anchors("Elle correspond en général à deux mois de loyer, soit 1 500 € pour un loyer de 750 €.", "amount")
    assert [(c["value"], c["currency"], c["unit"]) for c in caps] == [(2.0, None, "mois de loyer"), (1500.0, "EUR", None), (750.0, "EUR", None)]
    assert find_anchors("coûte 50 € et 12,50 EUR", "amount")[1]["value"] == 12.5


def test_anchor_dates_fr_en_iso_numeric():
    assert find_anchors("avant le 15 janvier 2025", "date")[0]["iso"] == "2025-01-15"
    assert find_anchors("on March 3, 2024", "date")[0]["iso"] == "2024-03-03"
    assert find_anchors("on 3 March 2024", "date")[0]["iso"] == "2024-03-03"
    assert find_anchors("ouvre le 2025-03-01", "date")[0]["iso"] == "2025-03-01"
    assert find_anchors("le 01/03/2025", "date")[0]["iso"] == "2025-03-01"
    assert find_anchors("le 2025-13-40", "date") == []


def test_anchor_phone_postal_url_duration():
    assert find_anchors("téléphone au +352 26 12 34 56.", "phone")[0]["raw"] == "+352 26 12 34 56"
    assert find_anchors("mobile 621 123 456", "phone")[0]["raw"] == "621 123 456"
    assert find_anchors("à L-3225 Bettembourg", "postal_code")[0]["raw"] == "l-3225"
    assert find_anchors("sur https://example.org/ct ou", "url")[0]["raw"] == "https://example.org/ct"
    assert find_anchors("dans les six mois après", "duration")[0] | {} == {"kind": "duration", "raw": "six mois", "pos": 9, "value": 6.0, "currency": None, "unit": "mois"}


def test_anchor_regex_detector_carries_capture_and_line():
    lines = line_records(make_tables().line_df, ["logement"])
    hits = anchor_regex(lines, "date")
    assert [(h.line_num, h.capture["iso"]) for h in hits] == [(14, "2025-01-15")]
    assert hits[0].method == "anchor_regex" and hits[0].concept_key == "anchor:date"


def test_row_match_reads_row_serialized_and_section():
    t = make_tables()
    hits = row_match(t.row_df, [term("loyer")], line_records(t.line_df))
    assert [(h.line_num, h.section_id, h.method) for h in hits] == [(7, "logement#s2", "row_match")]


def test_co_occurrence_line_and_section():
    lines = line_records(make_tables().line_df, ["logement"])
    hits = keyword_lines(lines, [term("garantie", concept="garantie_locative"), term("loyer", concept="loyer"), term("locataire", concept="locataire")])
    co_lines, co_sections = co_occurrence(hits)
    assert ("logement", 9) in co_lines  # garantie + locataire on one line
    assert ("logement", "logement#s3") in co_sections and ("logement", "logement#s2") in co_sections
    assert ("logement", 10) not in co_lines  # loyer alone on line 10


def test_current_page_boost_factor():
    assert current_page_boost(2.0, "logement", ["logement"]) == 2.6
    assert current_page_boost(2.0, "voiture", ["logement"]) == 2.0
    assert current_page_boost(2.0, "voiture", None) == 2.0


def test_required_anchor_kind_by_answer_type():
    assert required_anchor_kind("amount") == "amount" and required_anchor_kind("address") == "postal_code"
    assert required_anchor_kind("text") is None and required_anchor_kind("boolean") is None
