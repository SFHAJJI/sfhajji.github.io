"""SQLite: the index tables and the per-question audit tables.

The index tables mirror the DataFrames column for column (list columns are JSON text). The
audit tables hold what each brick passes to the next, one row per question, so every answer
can be replayed from its trace (SPEC §0.10). The other bricks write them; this module only
creates them and offers ``insert_row`` so they all write the same way.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ..parsing.tables import COLUMNS, SORT_KEYS, TABLE_NAMES

# Columns stored as JSON text, decoded back to lists on load.
JSON_COLUMNS = {"raw_files", "column_headers", "row_cells", "tags"}
BOOL_COLUMNS = {"is_heading"}

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS page_df (
  doc_id TEXT PRIMARY KEY, doc_order INTEGER NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
  lang TEXT NOT NULL, n_lines INTEGER NOT NULL, n_sections INTEGER NOT NULL, n_tables INTEGER NOT NULL,
  content_sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL, last_modified TEXT NOT NULL,
  parsing_method TEXT NOT NULL, kind TEXT NOT NULL, category TEXT NOT NULL, raw_files TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS line_df (
  doc_id TEXT NOT NULL, line_num INTEGER NOT NULL, text TEXT NOT NULL, element TEXT NOT NULL,
  section_id TEXT NOT NULL, anchor_id TEXT NOT NULL, css_path TEXT NOT NULL, char_count INTEGER NOT NULL,
  is_heading INTEGER NOT NULL, PRIMARY KEY (doc_id, line_num)
);
CREATE TABLE IF NOT EXISTS toc_df (
  doc_id TEXT NOT NULL, section_id TEXT PRIMARY KEY, level INTEGER NOT NULL, parent_id TEXT NOT NULL,
  title TEXT NOT NULL, breadcrumb TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
  anchor_id TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS row_df (
  doc_id TEXT NOT NULL, table_id TEXT NOT NULL, line_num INTEGER NOT NULL, line_end INTEGER NOT NULL,
  column_headers TEXT NOT NULL, row_cells TEXT NOT NULL, row_serialized TEXT NOT NULL,
  PRIMARY KEY (doc_id, table_id, line_num)
);
CREATE TABLE IF NOT EXISTS cross_ref_df (
  doc_id TEXT NOT NULL, line_num INTEGER NOT NULL, href TEXT NOT NULL, target_doc_id TEXT NOT NULL,
  target_anchor TEXT NOT NULL, context TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_index (
  doc_id TEXT PRIMARY KEY, doc_order INTEGER NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
  topic TEXT NOT NULL, summary_line TEXT NOT NULL, tags TEXT NOT NULL, n_lines INTEGER NOT NULL,
  lang TEXT NOT NULL, category TEXT NOT NULL, shape TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parse_coverage (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS line_df_section ON line_df (section_id);
CREATE INDEX IF NOT EXISTS toc_df_doc ON toc_df (doc_id);
CREATE INDEX IF NOT EXISTS cross_ref_target ON cross_ref_df (target_doc_id);
"""

# One row per question in each table; JSON text for the typed objects. The columns are the
# fields of SPEC §2 (ParsedQuestion, ExecutionPlan), §3 (RetrievalResult, RetrievedCandidate)
# and §4 (the answers and the _meta block).
AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
  question_id TEXT PRIMARY KEY, asked_at TEXT NOT NULL, original_question TEXT NOT NULL,
  pages_hint TEXT, language TEXT, index_version TEXT NOT NULL, pipeline_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parsed_questions (
  question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
  corrected_question TEXT NOT NULL, language TEXT NOT NULL, answer_shape TEXT NOT NULL, answer_type TEXT NOT NULL,
  keywords TEXT NOT NULL, structural_hints TEXT NOT NULL, scope_filters TEXT NOT NULL, decomposition TEXT NOT NULL,
  suggested_clarification TEXT, ambiguity_reason TEXT, candidate_values TEXT NOT NULL, proposed_default TEXT,
  parsing_notes TEXT NOT NULL, parsed_json TEXT NOT NULL, plan_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retrieval_results (
  question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
  methods_used TEXT NOT NULL, methods_skipped TEXT NOT NULL, not_found INTEGER NOT NULL, not_found_reason TEXT,
  confidence REAL, per_section_audit TEXT NOT NULL, sweep_rows TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS retrieved (
  question_id TEXT NOT NULL REFERENCES questions(question_id), candidate_id TEXT NOT NULL, rank INTEGER NOT NULL,
  doc_id TEXT NOT NULL, anchor_line_start INTEGER NOT NULL, anchor_line_end INTEGER NOT NULL,
  context_line_start INTEGER NOT NULL, context_line_end INTEGER NOT NULL, section_id TEXT NOT NULL,
  section_title TEXT NOT NULL, breadcrumb TEXT NOT NULL, url_anchor TEXT NOT NULL, snippet TEXT NOT NULL,
  text TEXT NOT NULL, methods TEXT NOT NULL, matched_keywords TEXT NOT NULL, role TEXT NOT NULL, reason TEXT NOT NULL,
  PRIMARY KEY (question_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS answers (
  question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
  answer_kind TEXT NOT NULL, answer_found INTEGER NOT NULL, complete_answer_found INTEGER NOT NULL,
  extraction_method TEXT NOT NULL, confidence REAL, caveats TEXT NOT NULL, items TEXT NOT NULL,
  context_structured TEXT, keywords_found TEXT NOT NULL, llm_discovered_keywords TEXT NOT NULL,
  conflicting_evidence TEXT, suggested_clarification TEXT, absence_reason TEXT, answer_json TEXT NOT NULL,
  validator_ok INTEGER NOT NULL, validator_report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_meta (
  question_id TEXT PRIMARY KEY REFERENCES questions(question_id),
  index_version TEXT NOT NULL, pipeline_version TEXT NOT NULL, methods_used TEXT NOT NULL,
  methods_skipped TEXT NOT NULL, activations TEXT NOT NULL, chunk_strategy TEXT NOT NULL, model_used TEXT NOT NULL,
  prompt_version TEXT NOT NULL, fragments_applied TEXT NOT NULL, iterations INTEGER NOT NULL,
  validator_report TEXT NOT NULL, timings_ms TEXT NOT NULL, meta_json TEXT NOT NULL
);
"""

AUDIT_TABLES = ("questions", "parsed_questions", "retrieval_results", "retrieved", "answers", "generation_meta")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (and create) the database with its schema."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(INDEX_SCHEMA + AUDIT_SCHEMA)
    conn.commit()


def _encode(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col in JSON_COLUMNS:
            out[col] = out[col].map(lambda v: json.dumps(list(v) if v is not None else [], ensure_ascii=False))
        elif col in BOOL_COLUMNS:
            out[col] = out[col].map(lambda v: 1 if bool(v) else 0)
    return out


def _decode(df: pd.DataFrame, name: str) -> pd.DataFrame:
    cols = COLUMNS.get(name) or list(df.columns)
    out = df[cols].copy()
    for col in out.columns:
        if col in JSON_COLUMNS:
            out[col] = out[col].map(lambda v: json.loads(v) if v else [])
        elif col in BOOL_COLUMNS:
            out[col] = out[col].map(bool)
    if len(out) and name in SORT_KEYS:
        out = out.sort_values(SORT_KEYS[name], kind="mergesort").reset_index(drop=True)
    return out


def save_index(conn: sqlite3.Connection, tables: dict[str, pd.DataFrame], coverage: dict[str, Any]) -> None:
    """Replace the index tables and the coverage, in one transaction."""
    try:
        for name in TABLE_NAMES:
            conn.execute(f"DELETE FROM {name}")
            df = _encode(tables[name])
            if len(df):
                cols = list(df.columns)
                placeholders = ",".join("?" for _ in cols)
                conn.executemany(
                    f"INSERT INTO {name} ({','.join(cols)}) VALUES ({placeholders})",
                    [tuple(_plain(v) for v in row) for row in df.itertuples(index=False, name=None)],
                )
        conn.execute("DELETE FROM parse_coverage")
        conn.executemany(
            "INSERT INTO parse_coverage (key, value) VALUES (?, ?)",
            [(k, json.dumps(v, ensure_ascii=False, sort_keys=True)) for k, v in sorted(coverage.items())],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _plain(v: Any) -> Any:
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        return v.item()
    return v


def load_index(conn: sqlite3.Connection) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """The tables back as DataFrames (same columns, same types), and the coverage dict."""
    tables = {}
    for name in TABLE_NAMES:
        df = pd.read_sql_query(f"SELECT * FROM {name}", conn)
        tables[name] = _decode(df, name)
    coverage = {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM parse_coverage")}
    return tables, coverage


def insert_row(conn: sqlite3.Connection, table: str, row: dict[str, Any], replace: bool = True) -> None:
    """Insert one audit row; dict/list values are stored as JSON text, booleans as 0/1."""
    if table not in AUDIT_TABLES:
        raise ValueError(f"not an audit table: {table}")
    values = []
    for v in row.values():
        if isinstance(v, (dict, list, tuple)):
            values.append(json.dumps(v, ensure_ascii=False, sort_keys=True))
        elif isinstance(v, bool):
            values.append(1 if v else 0)
        else:
            values.append(v)
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    conn.execute(f"{verb} INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", values)
    conn.commit()
