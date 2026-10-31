"""Builds from the fetched raw files under raw/, when they are present (no network)."""

import json
from pathlib import Path

import pytest

from guide_rag.parsing.documents import build_documents
from guide_rag.parsing.fetch import load_manifest
from guide_rag.parsing.tables import build_tables, index_version

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
INDEX = ROOT / "index"


def _raw_is_complete() -> bool:
    manifest = load_manifest(RAW)
    if manifest is None:
        return False
    return all((RAW / r["file"]).exists() for r in manifest["resources"] if r.get("file"))


pytestmark = pytest.mark.skipif(not _raw_is_complete(), reason="raw/manifest.json and its files are not present")


@pytest.fixture(scope="module")
def real_index():
    manifest = load_manifest(RAW)
    docs, data = build_documents(RAW, manifest)
    return build_tables(docs, data, site_url=manifest["site"])


def test_the_site_is_parsed_into_documents(real_index):
    page = real_index.tables["page_df"]
    kinds = page["kind"].value_counts().to_dict()
    assert kinds.get("fiche", 0) >= 30 and kinds.get("panel", 0) >= 5 and kinds.get("page", 0) >= 1
    assert page["n_lines"].sum() > 1000
    assert set(page["lang"]) == {"fr"}
    assert "vehicule" in set(page["doc_id"]) and "faq" in set(page["doc_id"])


def test_structure_invariants(real_index):
    t = real_index.tables
    sections = set(t["toc_df"]["section_id"])
    assert all(s == "" or s in sections for s in t["line_df"]["section_id"])
    assert (t["toc_df"]["end_line"] >= t["toc_df"]["start_line"]).all()
    assert set(t["cross_ref_df"]["target_doc_id"]) <= set(t["page_df"]["doc_id"])
    assert t["line_df"].groupby("doc_id")["line_num"].apply(lambda s: list(s) == list(range(1, len(s) + 1))).all()
    assert not (t["line_df"]["text"].str.strip() == "").any()
    assert set(t["line_df"]["element"]) <= {"h1", "h2", "h3", "h4", "p", "li", "td", "th", "caption", "blockquote", "dt", "dd"}


def test_guided_fiche_and_tables(real_index):
    t = real_index.tables
    veh = t["toc_df"][t["toc_df"]["doc_id"] == "vehicule"]
    assert "Immatriculer son véhicule › Étapes" in set(veh["breadcrumb"])
    rows = t["row_df"][t["row_df"]["doc_id"] == "vehicule"]
    assert any(r.startswith("Poste: Droit de chancellerie | Montant: 50 €") for r in rows["row_serialized"])


def test_committed_index_matches_the_code(real_index):
    """Guards against an index/*.json that drifted from the parser."""
    coverage_path = INDEX / "coverage.json"
    if not coverage_path.exists():
        pytest.skip("no built index")
    from guide_rag.storage.export_json import SUMMARY_FILE, apply_reviewed_summaries

    committed = json.loads(coverage_path.read_text(encoding="utf-8"))
    tables = dict(real_index.tables)
    # the build merges the reviewed summary lines before hashing; so must this check
    tables["corpus_index"], _ = apply_reviewed_summaries(tables["corpus_index"], INDEX / SUMMARY_FILE)
    assert committed["index_version"] == index_version(tables)
