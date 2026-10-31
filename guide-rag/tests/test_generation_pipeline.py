"""`answer_question` end to end: the happy path, the absence path, the retry and the rejection, replay, determinism."""

import json

from test_retrieval_fixtures import DICTIONARY, make_tables, plan_for, q_bail, q_garantie, q_immat_list, q_permis

from guide_rag.generation import pipeline
from guide_rag.generation.pipeline import answer_question, replay
from guide_rag.generation.schemas import AbsenceJustification, AmountAnswer, GenerationResult, TextAnswer


def test_amount_question_end_to_end():
    q = q_garantie()
    r = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert isinstance(r, GenerationResult) and isinstance(r.answer, AmountAnswer)
    assert r.answer.answer_found and r.answer.items[0].amount.model_dump() == {"value": 2.0, "currency": None, "unit": "mois de loyer"}
    assert r.trace.retrieval.candidates[0].candidate_id == "logement#l9-l10"
    assert r.trace.parsed["question_id"] == "q1" and r.trace.plan["activations"]["use_toc"]["on"] is True


def test_absence_path_when_not_found():
    q = q_permis()
    r = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert isinstance(r.answer, AbsenceJustification) and r.answer.reason == "concept_not_found"
    assert r.meta.validator_report == {"iteration_1": []} and r.meta.iterations == 1


def test_validator_failure_retries_once_then_passes(monkeypatch):
    real = pipeline.generate_verbatim
    calls = {"n": 0}

    def flaky(parsed, retrieval, tables):
        calls["n"] += 1
        a = real(parsed, retrieval, tables)
        if calls["n"] == 1:
            a.items[0].spans[0].quote = "a sentence the guide never wrote"
        return a

    monkeypatch.setattr(pipeline, "generate_verbatim", flaky)
    q = q_bail()
    r = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.meta.iterations == 2 and calls["n"] == 2
    assert [p.code for p in r.meta.validator_report["iteration_1"]] == ["quote_not_in_lines"]
    assert r.meta.validator_report["iteration_2"] == [] and r.answer.answer_found


def test_validator_failure_twice_gives_a_typed_not_answered(monkeypatch):
    real = pipeline.generate_verbatim

    def broken(parsed, retrieval, tables):
        a = real(parsed, retrieval, tables)
        a.items[0].spans[0].line_end = 1  # line_end < line_start, every time
        return a

    monkeypatch.setattr(pipeline, "generate_verbatim", broken)
    q = q_bail()
    r = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert isinstance(r.answer, TextAnswer) and r.answer.items == [] and not r.answer.answer_found
    assert r.answer.caveats[0].startswith("Rejected by the validator: line_end 1 < line_start 4")
    assert r.meta.iterations == 2 and len(r.meta.validator_report["iteration_2"]) == 1
    assert r.answer.context_structured[0].candidate_id == "logement#l4-l6"  # the trace still says where it looked


def test_replay_reproduces_the_answer_from_its_trace():
    q = q_immat_list()
    first = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    again = replay(first.model_dump_json(), make_tables(), DICTIONARY)
    assert again.meta.replay == {"source_question_id": "q1", "candidates_identical": True, "spans_identical": True, "index_version_identical": True}
    assert again.stable_json() == first.stable_json()
    assert replay(json.loads(first.model_dump_json()), make_tables(), DICTIONARY).answer == first.answer


def test_two_runs_give_identical_json():
    for q in (q_garantie(), q_bail(), q_immat_list(), q_permis()):
        a = answer_question(q, plan_for(q), make_tables(), DICTIONARY).stable_json()
        b = answer_question(q, plan_for(q), make_tables(), DICTIONARY).stable_json()
        assert a == b


def test_duck_typed_question_and_plan():
    parsed = {"question_id": "d2", "original_question": "le bail ?", "corrected_question": "le bail", "language": "fr",
              "keywords": [{"text": "bail", "weight": 1.0, "source": "direct", "concept": "bail", "is_regex": False}],
              "answer_shape": "single", "answer_type": "text",
              "structural_hints": {"pages_hint": ["logement"], "toc_section_hint": None, "answer_context": "paragraph"},
              "decomposition": {"pattern": "single", "sub_questions": []}}
    plan = {"activations": {"use_toc": {"on": True, "reason": "3+ sections"}, "current_page_boost": {"on": True, "reason": "pages_hint"}}}
    r = answer_question(parsed, plan, make_tables(), DICTIONARY)
    assert r.answer.answer_found and r.meta.question_id == "d2" and "current_page_boost" in r.meta.methods_used
    assert r.meta.activations["use_keywords"].reason == "keyword detectors always run"  # the default fills the gaps
