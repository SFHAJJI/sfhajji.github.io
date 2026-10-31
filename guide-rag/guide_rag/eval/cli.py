"""The `eval` command: the golden set through the four bricks, a report per question type."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from guide_rag.cli import register_command


def _parse_factory():
    from guide_rag.question.parse_question import parse_question

    def parse(question: str, tables, dictionary, page: str | None):
        return parse_question(question, line_df=tables.line_df, toc_df=tables.toc_df, corpus_index=tables.corpus_index,
                              dictionary=dictionary, current_page=page)

    return parse


def _dispatch_factory():
    from guide_rag.question.dispatcher import dispatch

    def run(parsed, tables):
        return dispatch(parsed, toc_df=tables.toc_df, llm_available=False, row_df=tables.row_df)

    return run


def _configure(p: argparse.ArgumentParser) -> None:
    p.add_argument("--index", default="index", help="the index directory (default: index)")
    p.add_argument("--golden", default="eval/golden.yaml", help="the golden set (default: eval/golden.yaml)")
    p.add_argument("--out", default="eval", help="where report.json and report.md go (default: eval/)")
    p.add_argument("--traces", action="store_true", help="also write one JSON trace per question under traces/")
    p.add_argument("--traces-dir", default="traces")
    p.add_argument("--fail-under", type=float, default=None, help="exit 1 when the ok rate is below this fraction")


def _run(args: argparse.Namespace) -> int:
    from guide_rag.generation.cli import load_tables
    from guide_rag.generation.pipeline import PIPELINE_VERSION
    from guide_rag.question.dictionary import Dictionary

    from .golden import load_golden
    from .run import report_markdown, run_eval, write_reports

    tables = load_tables(Path(args.index))
    dictionary = Dictionary.load()
    golden = load_golden(Path(args.golden))
    report = run_eval(tables, dictionary, golden, parse=_parse_factory(), dispatch=_dispatch_factory(), pipeline_version=PIPELINE_VERSION,
                      traces_dir=Path(args.traces_dir) if args.traces else None)
    json_path, md_path = write_reports(report, Path(args.out))
    print(report_markdown(report))
    print(f"written: {json_path}, {md_path}" + (f", traces in {args.traces_dir}/" if args.traces else ""))
    if report.totals["quote_fidelity"] is not None and report.totals["quote_fidelity"] < 1.0:
        print("quote fidelity below 100 %: a quote failed the validator", file=sys.stderr)
        return 1
    if args.fail_under is not None and (report.totals["ok"] or 0.0) < args.fail_under:
        return 1
    return 0


register_command("eval", "run the golden set and report per question type", _configure, _run)
