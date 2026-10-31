"""The evaluation module on the synthetic corpus: the golden file, the metrics per type, the reports and the traces."""

import json

import yaml
from test_retrieval_fixtures import DICTIONARY, expand, kw, make_tables, plan_for, pq

from guide_rag.eval.golden import GoldenQuestion, load_golden
from guide_rag.eval.run import evaluate_one, report_markdown, run_eval, summarise, write_reports


def _golden():
    return [GoldenQuestion.model_validate(g) for g in [
        {"id": "a1", "type": "amount", "question": "Combien coûte la garantie locative ?", "expected": {"doc_id": "logement", "sections": ["logement#s3"]}},
        {"id": "l1", "type": "listing", "question": "Quels documents pour l'immatriculation ?", "expected": {"doc_id": "voiture", "sections": ["Immatriculation"]}},
        {"id": "f1", "type": "factual", "question": "Qu'est-ce que le bail ?", "expected": {"doc_id": "logement", "lines": [4, 6]}},
        {"id": "x1", "type": "out-of-scope", "question": "Comment échanger mon permis de conduire ?", "expected": "absent"},
        {"id": "v1", "type": "vague", "question": "et ça ?", "expected": "clarify"},
        {"id": "w1", "type": "factual", "question": "Qu'est-ce que le bail ?", "expected": {"doc_id": "voiture", "sections": ["voiture#s2"]}, "note": "a wrong label, to see a FAIL"},
    ]]


QUESTIONS = {
    "Combien coûte la garantie locative ?": lambda: pq("Combien coûte la garantie locative ?", [kw("garantie", concept="garantie_locative"), *expand("garantie_locative")], answer_type="amount"),
    "Quels documents pour l'immatriculation ?": lambda: pq("Quels documents pour l'immatriculation ?", [kw("documents"), kw("immatriculation", concept="immatriculation"), *expand("immatriculation")], answer_shape="listing"),
    "Qu'est-ce que le bail ?": lambda: pq("Qu'est-ce que le bail ?", [kw("bail", concept="bail"), *expand("bail")]),
    "Comment échanger mon permis de conduire ?": lambda: pq("Comment échanger mon permis de conduire ?", [kw("échanger"), kw("permis", concept="permis"), *expand("permis")]),
    "et ça ?": lambda: pq("et ça ?", [kw("ça")], ambiguity_reason="pronoun_only", suggested_clarification="De quoi parlez-vous ?"),
}


def parse(question, tables, dictionary, page):
    return QUESTIONS[question]()


def dispatch(parsed, tables):
    return plan_for(parsed)


def test_load_golden_validates_and_rejects_duplicates(tmp_path):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "questions": [g.model_dump(mode="json") for g in _golden()[:2]]}, allow_unicode=True), encoding="utf-8")
    loaded = load_golden(path)
    assert [g.id for g in loaded] == ["a1", "l1"] and loaded[0].expected.doc_id == "logement"
    path.write_text(yaml.safe_dump({"questions": [{"id": "d", "type": "factual", "question": "x", "expected": "absent"}] * 2}), encoding="utf-8")
    try:
        load_golden(path)
    except ValueError as e:
        assert "repeats" in str(e)
    else:
        raise AssertionError("duplicate ids must be refused")


def test_evaluate_one_measures_hits_absence_and_clarification():
    t = make_tables()
    titles = {str(r["section_id"]): str(r["title"]) for r in t.toc_df.to_dict("records")}
    outcomes = {g.id: evaluate_one(g, t, DICTIONARY, parse=parse, dispatch=dispatch, toc_titles=titles)[0] for g in _golden()}
    assert outcomes["a1"].ok and outcomes["a1"].level0_hit and outcomes["a1"].retrieval_hit and outcomes["a1"].primary == "logement#l9-l10"
    assert outcomes["l1"].ok and outcomes["l1"].verdict == "answer"  # matched by section title
    assert outcomes["f1"].ok  # matched by line overlap
    assert outcomes["x1"].ok and outcomes["x1"].verdict.startswith("absent:") and outcomes["x1"].not_found_correct
    assert outcomes["v1"].ok and outcomes["v1"].clarification_fired
    assert not outcomes["w1"].ok and outcomes["w1"].retrieval_hit is False and outcomes["w1"].answer_found
    assert all(o.quote_fidelity for o in outcomes.values())


def test_summary_per_type_and_reports(tmp_path):
    t = make_tables()
    report = run_eval(t, DICTIONARY, _golden(), parse=parse, dispatch=dispatch, pipeline_version="test", traces_dir=tmp_path / "traces")
    assert set(report.per_type) == {"amount", "listing", "factual", "out-of-scope", "vague"}
    assert report.per_type["factual"]["n"] == 2 and report.per_type["factual"]["retrieval_hit"] == 0.5
    assert report.per_type["out-of-scope"]["not_found_correct"] == 1.0 and report.per_type["out-of-scope"]["level0_hit"] is None
    assert report.per_type["vague"]["clarification_fired"] == 1.0
    assert report.totals["n"] == 6 and report.totals["quote_fidelity"] == 1.0 and report.index_version == "idx-test-1"
    json_path, md_path = write_reports(report, tmp_path / "out")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert [q["id"] for q in data["questions"]] == ["a1", "l1", "f1", "x1", "v1", "w1"]
    md = md_path.read_text(encoding="utf-8")
    assert "| factual | 2 | 50 % |" in md and "| w1 | factual | FAIL |" in md
    assert report_markdown(report) == md
    # One trace per question, timings removed, replayable (it carries the parsed question and the plan).
    trace = json.loads((tmp_path / "traces" / "a1.json").read_text(encoding="utf-8"))
    assert "timings_ms" not in trace["meta"] and trace["trace"]["parsed"]["original_question"] == "Combien coûte la garantie locative ?"
    assert sorted(p.name for p in (tmp_path / "traces").iterdir()) == ["a1.json", "f1.json", "l1.json", "v1.json", "w1.json", "x1.json"]


def test_summarise_handles_an_empty_set():
    assert summarise([]) == ({}, {"n": 0, "ok": None, "quote_fidelity": None, "median_ms": None})
