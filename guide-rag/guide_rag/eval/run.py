"""Run the golden set through the four bricks and report per question type (SPEC §6).

Per type: level-0 routing hit (the expected page was kept), retrieval hit (the expected section is
among the primaries), answer_found rate, quote fidelity (the validator is clean on the final answer),
not-found correctness, clarification fire rate, median latency. One line per question, ok/fail
with the primary's id. `--traces` writes one JSON trace per question (the ask --json output without
timings) for replay and for the page's cross-check.
"""

from __future__ import annotations

import datetime as _dt
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from guide_rag.generation.pipeline import answer_question
from guide_rag.generation.schemas import AbsenceJustification, GenerationResult
from guide_rag.generation.validator import validate
from guide_rag.retrieval.text import fold

from .golden import GoldenQuestion, load_golden

TYPE_ORDER = ["factual", "listing", "amount", "date", "yes/no", "address/phone", "typo", "EN", "DE", "on-page", "compound", "vague", "out-of-scope"]
METRICS = ["level0_hit", "retrieval_hit", "answer_found", "quote_fidelity", "not_found_correct", "clarification_fired"]


@dataclass
class QuestionOutcome:
    id: str
    type: str
    question: str
    ok: bool
    verdict: str
    primary: str | None
    expected: str
    level0_hit: bool
    retrieval_hit: bool
    answer_found: bool
    quote_fidelity: bool
    not_found_correct: bool
    clarification_fired: bool
    ms: float
    note: str = ""

    def as_row(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class EvalReport:
    generated_at: str
    index_version: str | None
    pipeline_version: str
    per_type: dict[str, dict[str, Any]]
    totals: dict[str, Any]
    questions: list[QuestionOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "index_version": self.index_version,
            "pipeline_version": self.pipeline_version,
            "totals": self.totals,
            "per_type": self.per_type,
            "questions": [q.as_row() for q in self.questions],
        }


def _section_matches(candidate, expected, toc_titles: dict[str, str]) -> bool:
    """The expected section is the candidate's anchor section (by id or title), or its lines overlap."""
    if candidate.anchor.doc_id != expected.doc_id:
        return False
    if expected.lines:
        lo, hi = int(expected.lines[0]), int(expected.lines[-1])
        if candidate.anchor.line_end >= lo and candidate.anchor.line_start <= hi:
            return True
    if not expected.sections:
        return not expected.lines
    sid = candidate.anchor.section_id or ""
    title = fold(toc_titles.get(sid, ""))
    for s in expected.sections:
        if s == sid or fold(s) == title:
            return True
    return False


def _verdict(result: GenerationResult) -> str:
    a = result.answer
    if isinstance(a, AbsenceJustification):
        return "absent:" + a.reason
    if a.answer_found and a.complete_answer_found:
        return "answer"
    return "partial" if a.answer_found else "not_found"


def evaluate_one(golden: GoldenQuestion, tables, dictionary, *, parse, dispatch, toc_titles: dict[str, str]) -> tuple[QuestionOutcome, GenerationResult, Any]:
    parsed = parse(golden.question, tables, dictionary, golden.page)
    plan = dispatch(parsed, tables)
    result = answer_question(parsed, plan, tables, dictionary, index_version=tables.index_version)
    retrieval = result.trace.retrieval if result.trace else None
    answer = result.answer
    is_absence = isinstance(answer, AbsenceJustification)
    clarification = getattr(parsed, "ambiguity_reason", None) is not None
    primaries = retrieval.primaries if retrieval else []
    primary_id = primaries[0].candidate_id if primaries else None
    found = bool(getattr(answer, "answer_found", False))
    fidelity = validate(answer, tables.line_df, parsed) == [] and all(not v for v in result.meta.validator_report.values()) if found else True
    ms = float(result.meta.timings_ms.get("total", 0.0))

    if golden.expects_absence:
        ok = is_absence
        level0 = retrieval_hit = False
        nf_ok = is_absence or not found
        expected = "absent"
    elif golden.expects_clarification:
        ok = clarification
        level0 = retrieval_hit = False
        nf_ok = not found or is_absence or clarification
        expected = "clarify"
    else:
        exp = golden.expected
        level0 = bool(retrieval and any(p.doc_id == exp.doc_id for p in retrieval.route_pages))
        retrieval_hit = any(_section_matches(c, exp, toc_titles) for c in primaries)
        ok = retrieval_hit
        nf_ok = found and not is_absence
        expected = exp.doc_id + ("#" + "|".join(exp.sections) if exp.sections else "") + (f" l{exp.lines[0]}-{exp.lines[-1]}" if exp.lines else "")
    outcome = QuestionOutcome(
        id=golden.id, type=golden.type, question=golden.question, ok=ok, verdict=_verdict(result), primary=primary_id,
        expected=expected, level0_hit=level0, retrieval_hit=retrieval_hit, answer_found=found, quote_fidelity=fidelity,
        not_found_correct=nf_ok, clarification_fired=clarification, ms=round(ms, 1), note=golden.note or "",
    )
    return outcome, result, parsed


def _rate(values: list[bool]) -> float | None:
    return round(sum(1 for v in values if v) / len(values), 3) if values else None


def summarise(outcomes: list[QuestionOutcome]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    per_type: dict[str, dict[str, Any]] = {}
    for t in TYPE_ORDER + sorted({o.type for o in outcomes} - set(TYPE_ORDER)):
        rows = [o for o in outcomes if o.type == t]
        if not rows:
            continue
        routed = [o for o in rows if o.expected not in ("absent", "clarify")]
        per_type[t] = {
            "n": len(rows),
            "ok": _rate([o.ok for o in rows]),
            "level0_hit": _rate([o.level0_hit for o in routed]),
            "retrieval_hit": _rate([o.retrieval_hit for o in routed]),
            "answer_found": _rate([o.answer_found for o in rows]),
            "quote_fidelity": _rate([o.quote_fidelity for o in rows]),
            "not_found_correct": _rate([o.not_found_correct for o in rows]),
            "clarification_fired": _rate([o.clarification_fired for o in rows]),
            "median_ms": round(statistics.median([o.ms for o in rows]), 1),
        }
    totals = {
        "n": len(outcomes),
        "ok": _rate([o.ok for o in outcomes]),
        "quote_fidelity": _rate([o.quote_fidelity for o in outcomes]),
        "median_ms": round(statistics.median([o.ms for o in outcomes]), 1) if outcomes else None,
    }
    return per_type, totals


def run_eval(tables, dictionary, golden: list[GoldenQuestion] | None = None, *, parse, dispatch, pipeline_version: str,
             traces_dir: Path | None = None) -> EvalReport:
    golden = golden if golden is not None else load_golden()
    toc_titles = {str(r["section_id"]): str(r["title"]) for r in tables.toc_df[["section_id", "title"]].to_dict("records")}
    outcomes: list[QuestionOutcome] = []
    if traces_dir is not None:
        traces_dir.mkdir(parents=True, exist_ok=True)
    for g in golden:
        outcome, result, _ = evaluate_one(g, tables, dictionary, parse=parse, dispatch=dispatch, toc_titles=toc_titles)
        outcomes.append(outcome)
        if traces_dir is not None:
            data = result.model_dump(mode="json", exclude={"meta": {"timings_ms"}})
            (traces_dir / f"{g.id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    per_type, totals = summarise(outcomes)
    return EvalReport(
        generated_at=_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        index_version=tables.index_version,
        pipeline_version=pipeline_version,
        per_type=per_type,
        totals=totals,
        questions=outcomes,
    )


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f} %"


def report_markdown(report: EvalReport) -> str:
    lines = [
        "# Evaluation per question type",
        "",
        f"Generated {report.generated_at} on index `{(report.index_version or '')[:12]}` with pipeline `{report.pipeline_version}`.",
        f"{report.totals['n']} questions; ok {_pct(report.totals['ok'])}; quote fidelity {_pct(report.totals['quote_fidelity'])}; median {report.totals['median_ms']} ms.",
        "",
        "| type | n | ok | level-0 | retrieval | found | fidelity | not-found ok | clarify | median ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for t, m in report.per_type.items():
        lines.append(f"| {t} | {m['n']} | {_pct(m['ok'])} | {_pct(m['level0_hit'])} | {_pct(m['retrieval_hit'])} | {_pct(m['answer_found'])} | "
                     f"{_pct(m['quote_fidelity'])} | {_pct(m['not_found_correct'])} | {_pct(m['clarification_fired'])} | {m['median_ms']} |")
    lines += ["", "## Questions", "", "| id | type | ok | question | verdict | primary | expected |", "|---|---|---|---|---|---|---|"]
    for q in report.questions:
        lines.append(f"| {q.id} | {q.type} | {'ok' if q.ok else 'FAIL'} | {q.question} | {q.verdict} | {q.primary or '-'} | {q.expected} |")
    return "\n".join(lines) + "\n"


def write_reports(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "report.json", out_dir / "report.md"
    json_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report_markdown(report), encoding="utf-8")
    return json_path, md_path
