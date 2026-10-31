"""SQLite round trip, JSON export determinism, the summary-lines YAML, the audit tables."""

import json

from guide_rag.parsing.tables import TABLE_NAMES, dumps, to_records
from guide_rag.storage import export_json, sqlite


def test_sqlite_round_trip_keeps_every_table(tmp_path, tiny_tables, tiny_coverage):
    db = tmp_path / "guide.sqlite"
    with sqlite.connect(db) as conn:
        sqlite.save_index(conn, tiny_tables, tiny_coverage)
        loaded, coverage = sqlite.load_index(conn)
    assert coverage == tiny_coverage
    for name in TABLE_NAMES:
        assert to_records(loaded[name], name) == to_records(tiny_tables[name], name), name
    assert loaded["line_df"]["is_heading"].dtype == bool
    assert isinstance(loaded["row_df"]["row_cells"].iloc[0], list)
    # saving again replaces, never duplicates
    with sqlite.connect(db) as conn:
        sqlite.save_index(conn, tiny_tables, tiny_coverage)
        assert conn.execute("SELECT COUNT(*) FROM line_df").fetchone()[0] == len(tiny_tables["line_df"])


def test_audit_tables_exist_and_accept_rows(tmp_path):
    with sqlite.connect(tmp_path / "g.sqlite") as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"questions", "parsed_questions", "retrieved", "retrieval_results", "answers", "generation_meta"} <= names
        sqlite.insert_row(conn, "questions", {"question_id": "q1", "asked_at": "2026-10-31T00:00:00Z", "original_question": "Combien ?",
                                              "pages_hint": ["bail"], "language": "fr", "index_version": "abc", "pipeline_version": "guide-rag/0.1.0"})
        sqlite.insert_row(conn, "generation_meta", {"question_id": "q1", "index_version": "abc", "pipeline_version": "guide-rag/0.1.0",
                                                    "methods_used": ["keyword_lines"], "methods_skipped": {"use_embeddings": "no vocabulary mismatch expected"},
                                                    "activations": [], "chunk_strategy": "section", "model_used": "no model", "prompt_version": "none",
                                                    "fragments_applied": [], "iterations": 1, "validator_report": {}, "timings_ms": {"total": 3}, "meta_json": {}})
        row = conn.execute("SELECT pages_hint, index_version FROM questions WHERE question_id='q1'").fetchone()
        assert json.loads(row[0]) == ["bail"] and row[1] == "abc"
        assert json.loads(conn.execute("SELECT methods_skipped FROM generation_meta").fetchone()[0]) == {"use_embeddings": "no vocabulary mismatch expected"}


def test_export_json_is_compact_utf8_sorted_and_deterministic(tmp_path, tiny_tables, tiny_coverage):
    out = tmp_path / "index"
    written = export_json.export_index(tiny_tables, tiny_coverage, out)
    assert {p.name for p in written} == {f"{n}.json" for n in TABLE_NAMES} | {"coverage.json"}
    text = (out / "line_df.json").read_text(encoding="utf-8")
    assert text == dumps(to_records(tiny_tables["line_df"], "line_df")) and "é" in text and ": " not in text[:200]
    first = {p.name: p.read_bytes() for p in written}
    export_json.export_index(tiny_tables, tiny_coverage, out)
    assert {p.name: p.read_bytes() for p in written} == first
    records = json.loads(text)
    assert records == sorted(records, key=lambda r: (r["doc_id"], r["line_num"]))
    assert json.loads((out / "coverage.json").read_text(encoding="utf-8"))["index_version"] == tiny_coverage["index_version"]


def test_summary_lines_yaml_draft_and_review(tmp_path, tiny_tables):
    path = tmp_path / "summary_lines.yaml"
    ci = tiny_tables["corpus_index"]
    assert export_json.write_summary_lines(ci, path) is True
    assert export_json.write_summary_lines(ci, path) is False  # unchanged → not rewritten
    entries = export_json.load_summary_lines(path)
    assert set(entries) == set(ci["doc_id"]) and entries["bail"]["reviewed"] is False
    # a reviewer freezes one line
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["lines"]["bail"].update(reviewed=True, summary_line="Le bail. Mots du lecteur : caution, garantie.")
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    merged, n = export_json.apply_reviewed_summaries(ci, path)
    assert n == 1 and merged.set_index("doc_id").loc["bail", "summary_line"].startswith("Le bail. ")
    assert ci.set_index("doc_id").loc["bail", "summary_line"].startswith("Signer un bail.")  # the input is untouched
    export_json.write_summary_lines(merged, path)
    assert export_json.load_summary_lines(path)["bail"]["reviewed"] is True
