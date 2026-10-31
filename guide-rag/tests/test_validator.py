"""Every check of the validator (SPEC §4), one failing answer per check."""

from test_retrieval_fixtures import DICTIONARY, make_tables, plan_for, q_bail, q_edl_date, q_garantie, q_immat_list

from guide_rag.generation.schemas import AbsenceJustification, DateAnswer, DateValue, ListAnswer, Span, TextAnswer, TextItem
from guide_rag.generation.validator import validate
from guide_rag.generation.verbatim import generate_verbatim
from guide_rag.retrieval.result import retrieve

T = make_tables()


def good(q):
    return generate_verbatim(q, retrieve(q, plan_for(q), T, DICTIONARY), T)


def codes(answer, q):
    return [p.code for p in validate(answer, T.line_df, q)]


def test_a_sound_answer_passes_every_check():
    for q in (q_garantie(), q_bail(), q_edl_date(), q_immat_list()):
        assert codes(good(q), q) == []


def test_quote_not_in_the_cited_lines_is_rejected():
    q = q_bail()
    a = good(q)
    a.items[0].spans[0].quote = "Le bail dure neuf ans."
    assert codes(a, q) == ["quote_not_in_lines"]


def test_quote_matches_after_whitespace_normalisation():
    q = q_bail()
    a = good(q)
    a.items[0].spans[0].quote = "  Le bail   est le contrat\nde location  "
    assert codes(a, q) == []


def test_line_end_before_line_start_is_rejected():
    q = q_bail()
    a = good(q)
    a.items[0].spans[0].line_end = 3
    assert codes(a, q) == ["span_order"]


def test_span_outside_the_context_is_rejected():
    q = q_bail()
    a = good(q)
    a.items[0].spans[0].line_end = 99
    assert codes(a, q) == ["span_outside_context"]


def test_item_without_span_is_rejected():
    q = q_bail()
    a = good(q)
    a.items[0].spans = []
    assert codes(a, q) == ["missing_span"]


def test_verbatim_without_quote_is_rejected():
    q = q_bail()
    a = good(q)
    a.items[0].spans[0].quote = None
    assert codes(a, q) == ["verbatim_without_quote"]


def test_date_must_be_iso():
    q = q_edl_date()
    a = good(q)
    a.items[0].date = DateValue(iso="15/01/2025", original="15 janvier 2025")
    assert codes(a, q) == ["date_not_iso"]
    a.items[0].date = DateValue(iso="2025-02-30", original="30 février 2025")
    assert codes(a, q) == ["date_not_iso"]


def test_shape_must_match_the_question():
    q = q_immat_list()
    a = TextAnswer(items=[TextItem(text="Certificat de conformité", spans=[Span(doc_id="voiture", line_start=6, line_end=6, quote="Certificat de conformité")])],
                   extraction_method="verbatim", answer_found=True)
    assert codes(a, q) == ["shape_mismatch"]
    assert codes(DateAnswer(items=[]), q_garantie()) == ["shape_mismatch"]


def test_items_and_answer_found_must_agree():
    q = q_bail()
    a = good(q)
    a.answer_found = False
    a.complete_answer_found = False
    assert codes(a, q) == ["found_flag"]
    b = ListAnswer(items=[], answer_found=True)
    assert codes(b, q_immat_list()) == ["found_flag"]


def test_complete_requires_found():
    a = TextAnswer(items=[], answer_found=False, complete_answer_found=True)
    assert codes(a, q_bail()) == ["complete_without_found"]


def test_absence_passes_and_context_shapes_are_accepted():
    q = q_bail()
    assert validate(AbsenceJustification(reason="concept_not_found"), T.line_df, q) == []
    a = good(q)
    mapping = {(r["doc_id"], r["line_num"]): r["text"] for r in T.line_df.to_dict("records")}
    assert validate(a, mapping, q) == []
    assert validate(a, T.line_df.to_dict("records"), q) == []
    assert [p.code for p in validate(a, {}, q)] == ["span_outside_context"]
