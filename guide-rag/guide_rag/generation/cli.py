"""The `ask` and `trace` commands: the four bricks end to end on the built index, model-free unless a key is set."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from guide_rag.cli import register_command


def load_tables(index_dir: Path):
    """The brick-1 tables from the SQLite index, as the retrieval contract expects them."""
    from guide_rag.retrieval.contracts import Tables
    from guide_rag.storage.sqlite import connect, load_index

    conn = connect(index_dir / "guide.sqlite")
    tables, coverage = load_index(conn)
    conn.close()
    return Tables(
        line_df=tables["line_df"],
        toc_df=tables["toc_df"],
        row_df=tables.get("row_df"),
        corpus_index=tables.get("corpus_index"),
        page_df=tables.get("page_df"),
        cross_ref_df=tables.get("cross_ref_df"),
        parse_coverage=coverage,
        index_version=coverage.get("index_version"),
    )


def ask(question: str, *, index_dir: Path, page: str | None = None, use_llm: bool = False):
    """One question through the four bricks; returns the GenerationResult."""
    from guide_rag.generation.pipeline import answer_question
    from guide_rag.question.dictionary import Dictionary
    from guide_rag.question.dispatcher import dispatch
    from guide_rag.question.parse_question import parse_question

    tables = load_tables(index_dir)
    dictionary = Dictionary.load()
    parsed = parse_question(
        question,
        line_df=tables.line_df,
        toc_df=tables.toc_df,
        corpus_index=tables.corpus_index,
        dictionary=dictionary,
        current_page=page,
    )
    client = None
    if use_llm:
        from guide_rag.generation.llm import LLMClient

        client = LLMClient()  # raises NotConfigured without GUIDE_RAG_LLM_* in the environment
    plan = dispatch(parsed, toc_df=tables.toc_df, llm_available=client is not None, row_df=tables.row_df)
    return answer_question(parsed, plan, tables, dictionary, llm_client=client, index_version=tables.index_version)


def _configure_ask(p: argparse.ArgumentParser) -> None:
    p.add_argument("question")
    p.add_argument("--page", default=None, help="the doc_id of the page the reader is on")
    p.add_argument("--index", default="index", help="the index directory (default: index)")
    p.add_argument("--llm", action="store_true", help="use the configured model for the arbiter and generation")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")


def _run_ask(args: argparse.Namespace) -> int:
    result = ask(args.question, index_dir=Path(args.index), page=args.page, use_llm=args.llm)
    if args.json:
        print(result.model_dump_json(indent=2) if hasattr(result, "model_dump_json") else json.dumps(result, default=str, indent=2))
        return 0
    print(summary(result))
    return 0


def summary(result) -> str:
    """A few lines a person reads: the verdict, the items with their path, the trace in one line."""
    a = result.answer
    lines = []
    kind = getattr(a, "kind", type(a).__name__)
    if kind == "absence":
        lines.append(f"PAS DANS CE GUIDE ({a.reason})")
        for c in a.searched_concepts:
            lines.append(f"  cherché: {c.concept} [{', '.join(c.variants[:6])}] pages={c.pages_with_hits} lignes={c.line_hits}")
        for m in a.closest_mentions[:3]:
            lines.append(f"  proche: {m.doc_id}#l{m.line_num} «{m.snippet[:80]}» — {m.why_not_an_answer}")
        if a.suggestion:
            lines.append(f"  suggestion: {a.suggestion}")
    else:
        verdict = "RÉPONSE" if a.answer_found and a.complete_answer_found else ("RÉPONSE PARTIELLE" if a.answer_found else "NON TROUVÉ")
        lines.append(f"{verdict} [{kind}, {a.extraction_method}, conf {a.confidence}]")
        for it in a.items:
            value = getattr(it, "text", None) or getattr(it, "amount", None) or getattr(it, "date", None) or getattr(it, "boolean", None)
            for sp in it.spans:
                lines.append(f"  {sp.doc_id} l{sp.line_start}-{sp.line_end}: «{(sp.quote or str(value))[:140]}»")
        for c in a.caveats:
            lines.append(f"  caveat: {c}")
        if a.suggested_clarification:
            lines.append(f"  précisez: {a.suggested_clarification}")
    m = result.meta
    lines.append(f"  trace: methods={m.methods_used} model={m.model_used} iterations={m.iterations} validator={m.validator_report}")
    return "\n".join(lines)


def _configure_trace(p: argparse.ArgumentParser) -> None:
    p.add_argument("trace_file", help="a saved trace JSON (from ask --json)")
    p.add_argument("--index", default="index")


def _run_trace(args: argparse.Namespace) -> int:
    from guide_rag.generation.pipeline import replay
    from guide_rag.question.dictionary import Dictionary

    tables = load_tables(Path(args.index))
    result = replay(Path(args.trace_file).read_text(encoding="utf-8"), tables, Dictionary.load())
    print(summary(result))
    print(f"  replay: {result.meta.replay}")
    return 0


register_command("ask", "ask the guide one question", _configure_ask, _run_ask)
register_command("trace", "replay a saved trace against the index", _configure_trace, _run_trace)
