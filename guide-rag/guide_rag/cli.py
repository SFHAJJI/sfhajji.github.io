"""``guide-rag``: the command line.

Brick 1 owns ``build`` (fetch → tables → sqlite → json) and ``export`` (sqlite → json). The
other bricks add ``ask``, ``eval`` and ``trace`` through ``register_command`` (see the marked
block below); this module runs without them.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import Callable

from . import PIPELINE_VERSION, __version__
from .parsing.documents import build_documents
from .parsing.fetch import SITE_URL, Fetcher, compare_manifests, is_fresh, load_manifest
from .parsing.tables import build_tables, index_version
from .storage import export_json, sqlite

# ----------------------------------------------------------------------------- registry
# ask / eval / trace: the question, retrieval and evaluation bricks register here.
# Each one calls register_command("ask", configure, run) where configure(parser) adds the
# arguments and run(args) -> int does the work. Modules listed in OPTIONAL_COMMAND_MODULES are
# imported if present, so brick 1 works alone and the others plug in without editing this file.
Configure = Callable[[argparse.ArgumentParser], None]
Run = Callable[[argparse.Namespace], int]
COMMANDS: dict[str, tuple[str, Configure, Run]] = {}
OPTIONAL_COMMAND_MODULES = ("guide_rag.question.cli", "guide_rag.retrieval.cli", "guide_rag.generation.cli", "guide_rag.eval.cli")


def register_command(name: str, help_text: str, configure: Configure, run: Run) -> None:
    COMMANDS[name] = (help_text, configure, run)


def _load_optional_commands() -> None:
    for module in OPTIONAL_COMMAND_MODULES:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name and module.startswith(exc.name):
                continue  # the brick is not there yet
            raise


# ----------------------------------------------------------------------------- build


def _configure_build(p: argparse.ArgumentParser) -> None:
    p.add_argument("--raw", default="raw", help="where the fetched files live (default raw/)")
    p.add_argument("--index", default="index", help="where the sqlite and json go (default index/)")
    p.add_argument("--site", default=SITE_URL, help="the site to fetch")
    p.add_argument("--refetch", action="store_true", help="fetch even when raw/manifest.json is fresh")
    p.add_argument("--max-age-days", type=int, default=7, help="a manifest older than this is refetched")
    p.add_argument("--offline", action="store_true", help="never fetch; fail if there is no manifest")
    p.add_argument("--quiet", action="store_true")


def run_build(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    raw_dir, index_dir = Path(args.raw), Path(args.index)
    say = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))

    # Not fresh = no manifest, too old, or a file missing or changed (a clean clone has the
    # manifest and none of the files): then fetch again, and compare with what we had.
    fresh, why = is_fresh(raw_dir, args.max_age_days)
    fetch_note = f"raw/ kept ({why})"
    drift: dict[str, list[str]] = {}
    if args.refetch or not fresh:
        if args.offline:
            if load_manifest(raw_dir) is None:
                print(f"error: --offline and no manifest in {raw_dir}", file=sys.stderr)
                return 2
            fetch_note = f"raw/ kept, offline ({why})"
        else:
            say(f"fetching {args.site} ({'refetch asked' if args.refetch else why})")
            previous = load_manifest(raw_dir)
            fetcher = Fetcher(raw_dir, site_url=args.site, log=say)
            manifest = fetcher.crawl()
            drift = compare_manifests(previous, manifest)
            fetch_note = f"fetched {manifest['pages_total']} pages in {manifest['requests']} requests"
            if previous is None:
                fetch_note += ", first manifest"
            elif drift["changed"] or drift["gone"] or drift["new"]:
                fetch_note += f", DRIFT since the previous manifest: {len(drift['changed'])} changed, {len(drift['gone'])} gone, {len(drift['new'])} new"
            else:
                fetch_note += f", {len(drift['verified'])} files verified against the previous manifest (same sha256)"
    manifest = load_manifest(raw_dir)
    if manifest is None:
        print(f"error: no manifest in {raw_dir}", file=sys.stderr)
        return 2

    documents, data = build_documents(raw_dir, manifest)
    built = build_tables(documents, data, site_url=manifest.get("site", args.site), pipeline_version=PIPELINE_VERSION)

    # The reviewed summary lines win over the drafts, so they must be merged before hashing.
    summary_path = index_dir / export_json.SUMMARY_FILE
    built.tables["corpus_index"], n_reviewed = export_json.apply_reviewed_summaries(built.tables["corpus_index"], summary_path)
    built.coverage["index_version"] = index_version(built.tables)
    built.coverage["summary_lines_reviewed"] = n_reviewed
    built.coverage["raw_drift"] = {k: v for k, v in drift.items() if k != "verified"} if drift else {}

    with sqlite.connect(index_dir / "guide.sqlite") as conn:
        sqlite.save_index(conn, built.tables, built.coverage)
    export_json.export_index(built.tables, built.coverage, index_dir)
    export_json.write_summary_lines(built.tables["corpus_index"], summary_path)

    c = built.coverage
    elapsed = time.perf_counter() - t0
    print("guide-rag build")
    print(f"  source:     {fetch_note}")
    for kind in ("changed", "gone", "new"):
        for item in drift.get(kind, []):
            print(f"  drift:      {kind}: {item}")
    print(f"  pages:      {c['pages_total']} ({c['pages_with_text']} with text; {c['documents']['panel']} panels, {c['documents']['fiche']} fiches, {c['documents']['page']} pages)")
    print(f"  lines:      {c['lines_total']}")
    print(f"  sections:   {c['sections_total']}")
    print(f"  tables:     {c['tables_total']} ({c['table_rows_total']} rows)")
    print(f"  cross-refs: {c['cross_refs']}")
    for note in c.get("data_scripts", []):
        print(f"  data:       {note}")
    print(f"  index:      {index_dir / 'guide.sqlite'}, {index_dir}/*.json, {summary_path.name} ({n_reviewed} reviewed)")
    print(f"  version:    {c['index_version']}")
    print(f"  elapsed:    {elapsed:.1f} s")
    return 0


# ----------------------------------------------------------------------------- export


def _configure_export(p: argparse.ArgumentParser) -> None:
    p.add_argument("--index", default="index", help="the directory with guide.sqlite (default index/)")
    p.add_argument("--out", default=None, help="where to write the json (default: the index directory)")


def run_export(args: argparse.Namespace) -> int:
    index_dir = Path(args.index)
    db = index_dir / "guide.sqlite"
    if not db.exists():
        print(f"error: {db} not found; run `guide-rag build` first", file=sys.stderr)
        return 2
    with sqlite.connect(db) as conn:
        tables, coverage = sqlite.load_index(conn)
    out = Path(args.out) if args.out else index_dir
    written = export_json.export_index(tables, coverage, out)
    print(f"guide-rag export: {len(written)} files in {out} (index_version {coverage.get('index_version', '')[:12]}…)")
    return 0


# ----------------------------------------------------------------------------- main

register_command("build", "fetch the site, build the tables, save sqlite and json", _configure_build, run_build)
register_command("export", "re-export index/*.json from index/guide.sqlite", _configure_export, run_export)


def main(argv: list[str] | None = None) -> int:
    _load_optional_commands()
    parser = argparse.ArgumentParser(prog="guide-rag", description="a documentary chatbot over a public guide")
    parser.add_argument("--version", action="version", version=f"guide-rag {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, configure, _) in COMMANDS.items():
        configure(sub.add_parser(name, help=help_text))
    args = parser.parse_args(argv)
    return COMMANDS[args.command][2](args)


if __name__ == "__main__":
    sys.exit(main())
