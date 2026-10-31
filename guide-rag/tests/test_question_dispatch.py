"""dispatcher.py and briefs.py: every activation has a reason; the two briefs do not overlap."""

from __future__ import annotations

import pandas as pd
import pytest

from guide_rag.question import ExecutionPlan, dispatch, generation_brief, parse_question, retrieval_brief

try:
    from test_question_fixtures import dictionary, tables  # noqa: F401
except ImportError:  # pragma: no cover
    from tests.test_question_fixtures import dictionary, tables  # noqa: F401


@pytest.fixture
def parse(tables, dictionary):
    def _parse(question: str, current_page: str | None = None):
        return parse_question(
            question,
            line_df=tables["line_df"],
            toc_df=tables["toc_df"],
            corpus_index=tables["corpus_index"],
            dictionary=dictionary,
            current_page=current_page,
        )

    return _parse


def test_every_flag_has_on_and_a_reason(parse, tables):
    plan = dispatch(parse("Combien coûte le contrôle technique ?"), toc_df=tables["toc_df"])
    acts = plan.activations()
    assert set(acts) == {
        "use_keywords", "use_toc", "use_row_level", "use_embeddings", "use_llm_arbiter",
        "use_llm_generation", "sweep_for_absence", "current_page_boost",
    }
    for name, a in acts.items():
        assert isinstance(a["on"], bool) and a["reason"], name


def test_keywords_and_sweep_always_on_embeddings_always_off(parse, tables):
    plan = dispatch(parse("bonjour merci"), toc_df=tables["toc_df"])
    assert plan.use_keywords.on and plan.sweep_for_absence.on
    assert not plan.use_embeddings.on and "keywords prove absence" in plan.use_embeddings.reason


def test_use_toc_needs_three_sections(parse, tables):
    p = parse("Combien coûte le contrôle technique ?")
    assert dispatch(p, toc_df=tables["toc_df"]).use_toc.on
    assert not dispatch(p, toc_df=tables["toc_df"].head(2)).use_toc.on
    assert not dispatch(p, toc_df=None).use_toc.on


def test_use_row_level_for_amount_date_or_a_named_column(parse, tables):
    assert dispatch(parse("Combien coûte le contrôle technique ?"), toc_df=tables["toc_df"]).use_row_level.on
    assert dispatch(parse("Quand est le prochain contrôle technique ?"), toc_df=tables["toc_df"]).use_row_level.on
    text = parse("Quelle prestation est faite ?")
    assert not dispatch(text, toc_df=tables["toc_df"]).use_row_level.on
    with_rows = dispatch(text, toc_df=tables["toc_df"], row_df=tables["row_df"])
    assert with_rows.use_row_level.on and "prestation" in with_rows.use_row_level.reason.lower()


def test_llm_flags_follow_the_key(parse, tables):
    p = parse("Comment se passe l'état des lieux ?")
    off = dispatch(p, toc_df=tables["toc_df"])
    on = dispatch(p, toc_df=tables["toc_df"], llm_available=True)
    assert not off.use_llm_arbiter.on and not off.use_llm_generation.on
    assert on.use_llm_arbiter.on and on.use_llm_generation.on


def test_current_page_boost_follows_pages_hint(parse, tables):
    assert dispatch(parse("loyer", current_page="logement"), toc_df=tables["toc_df"]).current_page_boost.on
    assert not dispatch(parse("loyer"), toc_df=tables["toc_df"]).current_page_boost.on


@pytest.mark.parametrize(
    "question, context, chunk",
    [
        ("Quels documents pour l'état des lieux ?", "section", "combined"),
        ("Combien coûte le contrôle technique ?", "line", "sequential"),
        ("Est-ce que la garantie locative est obligatoire ?", "line", "sequential"),
        ("Comment se passe l'état des lieux ?", "paragraph", "sequential"),
    ],
)
def test_answer_context_and_chunk_strategy_by_shape(parse, tables, question, context, chunk):
    plan = dispatch(parse(question), toc_df=tables["toc_df"])
    assert plan.answer_context == context and plan.chunk_strategy == chunk
    assert plan.answer_context_reason and plan.chunk_strategy_reason


def test_plan_is_deterministic_and_serialisable(parse, tables):
    p = parse("Combien coûte le contrôle technique ?", current_page="voiture")
    a = dispatch(p, toc_df=tables["toc_df"]).model_dump_json()
    b = dispatch(p, toc_df=tables["toc_df"]).model_dump_json()
    assert a == b
    assert ExecutionPlan.model_validate_json(a).question_id == p.question_id


def test_retrieval_brief_has_keywords_not_the_original_wording(parse):
    p = parse("Combien coûte la garantie locative et quand dois-je m'inscrire à la commune ?", current_page="logement")
    brief = retrieval_brief(p)
    dumped = brief.model_dump()
    assert "original_question" not in dumped
    assert brief.rewrites[0] == p.corrected_question and len(brief.rewrites) == 3
    assert all(not k.is_regex for k in brief.keywords) and all(k.is_regex for k in brief.anchors)
    assert brief.scope.pages_hint == ["logement"] and brief.scope.answer_type == "amount"


def test_generation_brief_has_the_wording_and_constraint_not_the_keywords(parse):
    p = parse("registration", current_page="commune")
    brief = generation_brief(p)
    dumped = brief.model_dump()
    assert "keywords" not in dumped and "anchors" not in dumped
    assert brief.original_question == "registration"
    assert brief.disambiguation is not None and brief.disambiguation.proposed_default == "declaration_arrivee"
    listing = generation_brief(parse("Quels documents pour l'état des lieux ?"))
    assert listing.format_constraint.startswith("a list") and listing.disambiguation is None
