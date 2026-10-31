"""JSON export of the index (``index/*.json``) and the router's summary lines (YAML).

Compact UTF-8 JSON, keys sorted, rows sorted by their keys: the same tables give the same
bytes. ``summary_lines.yaml`` is the hand-reviewed asset of SPEC §2b: the build drafts it,
a reviewer sets ``reviewed: true`` on a line to freeze it, and later builds keep that line
instead of their draft.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..parsing.tables import TABLE_NAMES, dumps, to_records

FILES = {name: f"{name}.json" for name in TABLE_NAMES}
FILES["coverage"] = "coverage.json"
SUMMARY_FILE = "summary_lines.yaml"


def export_index(tables: dict[str, pd.DataFrame], coverage: dict[str, Any], index_dir: Path | str) -> list[Path]:
    """Write the six tables and ``coverage.json``; return the paths written."""
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in TABLE_NAMES:
        path = index_dir / FILES[name]
        path.write_text(dumps(to_records(tables[name], name)), encoding="utf-8", newline="\n")
        written.append(path)
    path = index_dir / FILES["coverage"]
    path.write_text(dumps(coverage), encoding="utf-8", newline="\n")
    written.append(path)
    return written


def load_summary_lines(path: Path | str) -> dict[str, dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lines = data.get("lines") or {}
    return {str(k): dict(v or {}) for k, v in lines.items()}


def apply_reviewed_summaries(corpus_index: pd.DataFrame, path: Path | str) -> tuple[pd.DataFrame, int]:
    """Replace the drafted ``summary_line`` by the reviewed one where ``reviewed: true``."""
    existing = load_summary_lines(path)
    if not existing:
        return corpus_index, 0
    df = corpus_index.copy()
    n = 0
    for i, doc_id in enumerate(df["doc_id"]):
        entry = existing.get(doc_id)
        if entry and entry.get("reviewed") and entry.get("summary_line"):
            df.at[i, "summary_line"] = str(entry["summary_line"]).strip()
            n += 1
    return df, n


def write_summary_lines(corpus_index: pd.DataFrame, path: Path | str) -> bool:
    """Write the YAML: reviewed entries kept as they are, the others refreshed from the draft.

    Returns True when the file changed.
    """
    path = Path(path)
    existing = load_summary_lines(path)
    lines: dict[str, Any] = {}
    for rec in to_records(corpus_index, "corpus_index"):
        old = existing.get(rec["doc_id"]) or {}
        if old.get("reviewed"):
            lines[rec["doc_id"]] = {"title": rec["title"], "reviewed": True, "summary_line": old.get("summary_line", rec["summary_line"])}
        else:
            lines[rec["doc_id"]] = {"title": rec["title"], "reviewed": False, "summary_line": rec["summary_line"]}
    header = (
        "# Level-0 summary lines for the router (SPEC 2b), one per document.\n"
        "# Drafted by `guide-rag build`; review them like a schema, not like copy.\n"
        "# Set `reviewed: true` to freeze a line: later builds keep it instead of their draft.\n"
    )
    body = yaml.safe_dump({"version": 1, "lines": lines}, allow_unicode=True, sort_keys=False, width=110)
    text = header + body
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
