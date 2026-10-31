"""Export the dictionary assets for the page: ``dictionary/*.yaml`` -> ``web/data/dictionary.json``.

The index itself is exported by ``guide_rag/storage/export_json.py`` (``index/*.json``); this step
only converts the YAML the browser cannot read: the concepts, the keyword variants, the
abbreviations and the weak words. The values are stringified the way brick 2 reads them
(``str(row["keyword"])``), so the JS port and the Python pipeline see the same strings.

    python web/build_data.py            # writes web/data/dictionary.json, prints the counts
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY_DIR = ROOT / "dictionary"
OUT = ROOT / "web" / "data" / "dictionary.json"

KNOWN = {
    "concepts.yaml": ("concepts", "concepts"),
    "keywords.yaml": ("keywords", "keywords"),
    "abbreviations.yaml": ("abbreviations", "abbreviations"),
    "weak_words.yaml": ("weak_words", "weak_words"),
}


def _load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build(dictionary_dir: Path = DICTIONARY_DIR, out: Path = OUT) -> dict:
    data: dict = {"built_from": {}}
    for path in sorted(dictionary_dir.glob("*.yaml")):
        raw = _load(path)
        data["built_from"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in KNOWN:
            top_key, out_key = KNOWN[path.name]
            value = raw.get(top_key) if isinstance(raw, dict) else raw
        else:
            out_key, value = path.stem, raw
        data[out_key] = _stringify(out_key, value)
    data.setdefault("concepts", [])
    data.setdefault("keywords", [])
    data.setdefault("abbreviations", [])
    data.setdefault("weak_words", {})
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if not out.exists() or out.read_text(encoding="utf-8") != text:
        out.write_text(text, encoding="utf-8", newline="\n")
    return data


def _stringify(key: str, value):
    """The string columns as brick 2 reads them; everything else as YAML gave it."""
    if key == "concepts":
        return [{"concept": str(r["concept"]), "topic": str(r["topic"]), "definition": str(r.get("definition", ""))} for r in value or []]
    if key == "keywords":
        return [
            {"concept": str(r["concept"]), "language": str(r["language"]), "keyword": str(r["keyword"]),
             "priority": str(r["priority"]), "weight": float(r["weight"])}
            for r in value or []
        ]
    if key == "abbreviations":
        return [
            {"abbreviation": str(r["abbreviation"]), "expansion": str(r["expansion"]),
             "language": r.get("language"), "note": r.get("note")}
            for r in value or []
        ]
    if key == "weak_words":
        return {str(lang): [str(w) for w in (words or [])] for lang, words in (value or {}).items()}
    return value


def main(argv: list[str] | None = None) -> int:
    data = build()
    counts = {k: len(v) for k, v in data.items() if isinstance(v, (list, dict)) and k != "built_from"}
    print(f"web/build_data: {OUT.relative_to(ROOT)} {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
