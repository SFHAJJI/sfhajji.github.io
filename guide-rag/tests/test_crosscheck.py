"""The cross-check of SPEC §5: the golden questions (eval/golden.yaml when present, else a fixed
list) run through the Python pipeline and through the JS port under node, and the two must agree on
the ParsedQuestion keywords (text + source), the kept pages, the candidate ids and roles, the item
spans and the verdict. Node 18+ is required; the test skips with a reason when node is absent."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "index"
RUNNER = ROOT / "web" / "engine" / "node_runner.mjs"

FIXED_QUESTIONS = [
    {"question": "Comment immatriculer ma voiture ?", "page": None},
    {"question": "Combien coûte la garantie locative ?", "page": None},
    {"question": "Quels documents pour la déclaration d'arrivée ?", "page": None},
    {"question": "Quand faut-il faire le contrôle technique ?", "page": None},
    {"question": "Est-ce que je dois souscrire une assurance responsabilité civile ?", "page": None},
    {"question": "Combien de temps pour échanger mon permis de conduire ?", "page": None},
    {"question": "How do I register at the commune?", "page": None},
    {"question": "Wie melde ich mein Auto an?", "page": None},
    {"question": "garantie", "page": None},
    {"question": "immatriculaton de ma voitrue", "page": None},
    {"question": "Où trouver un médecin et comment obtenir la carte de sécurité sociale ?", "page": None},
    {"question": "Quel est le prix d'un abonnement Netflix ?", "page": None},
    {"question": "Combien de mois de caution ?", "page": "bail"},
]


def load_questions() -> list[dict]:
    """eval/golden.yaml in any of its likely shapes, else the fixed list."""
    golden = ROOT / "eval" / "golden.yaml"
    if not golden.exists():
        return FIXED_QUESTIONS
    raw = yaml.safe_load(golden.read_text(encoding="utf-8")) or {}
    items = raw.get("questions", raw) if isinstance(raw, dict) else raw
    out = []
    for item in items or []:
        if isinstance(item, str):
            out.append({"question": item, "page": None})
            continue
        question = item.get("question") or item.get("q") or item.get("text")
        if not question:
            continue
        page = item.get("page") or item.get("current_page")
        if page is None:
            hint = item.get("pages_hint")
            page = hint[0] if isinstance(hint, list) and hint else hint
        out.append({"question": str(question), "page": str(page) if page else None})
    return out or FIXED_QUESTIONS


def verdict_of(answer: dict) -> str:
    if answer.get("kind") == "absence":
        return "absence"
    if answer["answer_found"] and answer["complete_answer_found"]:
        return "complete"
    return "partial" if answer["answer_found"] else "not_found"


def summary(result: dict) -> dict:
    """The fields the cross-check compares, from a GenerationResult as JSON."""
    trace = result["trace"]
    retrieval = trace["retrieval"]
    answer = result["answer"]
    spans = [] if answer.get("kind") == "absence" else [
        (s["doc_id"], s["line_start"], s["line_end"]) for item in answer["items"] for s in item["spans"]
    ]
    return {
        "keywords": [(k["text"], k["source"]) for k in trace["parsed"]["keywords"]],
        "kept_pages": [p["doc_id"] for p in retrieval["route_pages"]],
        "candidates": [(c["candidate_id"], c["role"]) for c in retrieval["candidates"]],
        "spans": spans,
        "verdict": verdict_of(answer),
    }


def run_python(questions: list[dict]) -> list[dict]:
    from guide_rag.generation.cli import ask

    out = []
    for q in questions:
        result = ask(q["question"], index_dir=INDEX_DIR, page=q["page"])
        out.append(json.loads(result.model_dump_json()))
    return out


def run_js(questions: list[dict], tmp_path: Path) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed: the JS cross-check cannot run")
    questions_file = tmp_path / "questions.json"
    questions_file.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [node, str(RUNNER), str(questions_file), str(ROOT)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=300, cwd=str(ROOT),
    )
    assert proc.returncode == 0, f"node runner failed:\n{proc.stderr[-4000:]}"
    return [row["result"] for row in json.loads(proc.stdout)]


@pytest.fixture(scope="module")
def dictionary_json_built():
    sys.path.insert(0, str(ROOT / "web"))
    try:
        import build_data

        build_data.build()
    finally:
        sys.path.pop(0)


def test_python_and_js_agree_on_every_question(tmp_path, dictionary_json_built):
    questions = load_questions()
    assert len(questions) >= 12, "the cross-check needs at least a dozen questions"
    py = run_python(questions)
    js = run_js(questions, tmp_path)
    assert len(js) == len(py)
    mismatches = []
    for q, p, j in zip(questions, py, js):
        sp, sj = summary(p), summary(j)
        for field in sp:
            if sp[field] != sj[field]:
                mismatches.append(f"{q['question']!r} (page={q['page']}): {field}\n    python: {sp[field]}\n    js:     {sj[field]}")
    assert not mismatches, "the JS port diverges from the Python pipeline:\n" + "\n".join(mismatches)


def test_question_ids_and_index_version_agree(tmp_path, dictionary_json_built):
    questions = load_questions()[:3]
    py = run_python(questions)
    js = run_js(questions, tmp_path)
    for p, j in zip(py, js):
        assert p["meta"]["question_id"] == j["meta"]["question_id"]
        assert p["meta"]["index_version"] == j["meta"]["index_version"]
        assert p["meta"]["model_used"] == j["meta"]["model_used"] == "no model"
        assert p["meta"]["validator_report"] == j["meta"]["validator_report"]
