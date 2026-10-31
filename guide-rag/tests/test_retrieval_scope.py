"""Anchor -> context: runs, the three context sizes, and the invariant "context contains anchor"."""

from test_retrieval_fixtures import DICTIONARY, make_tables, plan_for, q_bail, q_edl_date, q_garantie, q_immat_list

from guide_rag.retrieval.result import retrieve
from guide_rag.retrieval.scope import anchor_runs, contains, context_for, is_whole_section, section_bounds


def test_anchor_runs_group_close_lines():
    assert anchor_runs([4, 5, 6, 11]) == [(4, 6), (11, 11)]
    assert anchor_runs([9, 6, 4]) == [(4, 6), (9, 9)]  # a gap of 2 still joins; order does not matter
    assert anchor_runs([]) == []


def test_context_sizes_per_answer_context():
    b = section_bounds(make_tables().toc_df)[("logement", "logement#s3")]
    assert context_for((9, 10), b, "line") == (9, 10)
    assert context_for((9, 10), b, "paragraph") == (8, 11)  # ±3 clipped to the section 8..11
    assert context_for((9, 10), b, "section") == (8, 11)
    b4 = section_bounds(make_tables().toc_df)[("logement", "logement#s4")]
    assert context_for((14, 14), b4, "paragraph") == (12, 16)


def test_context_always_contains_anchor_even_outside_bounds():
    b = section_bounds(make_tables().toc_df)[("logement", "logement#s3")]
    ctx = context_for((20, 21), b, "section")
    assert contains(ctx, (20, 21)) and ctx == (8, 21)
    assert contains(context_for((2, 2), None, "paragraph", page_last_line=16), (2, 2))


def test_every_candidate_keeps_the_invariant():
    t = make_tables()
    for q in (q_garantie(), q_bail(), q_edl_date(), q_immat_list()):
        for c in retrieve(q, plan_for(q), t, DICTIONARY).candidates:
            assert c.context.line_start <= c.anchor.line_start <= c.anchor.line_end <= c.context.line_end
            assert c.context.doc_id == c.anchor.doc_id


def test_is_whole_section():
    b = section_bounds(make_tables().toc_df)[("logement", "logement#s2")]
    assert is_whole_section((3, 7), b) and not is_whole_section((4, 7), b) and not is_whole_section((3, 7), None)
