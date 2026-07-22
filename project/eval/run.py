"""Eval runner — execute every case against the BI Analyst Agent and score it.

Flow:
    for each case:
        compute ground truth (run expected_sql via the SQL tool, when present)
        run the agent: ask(question) -> AnalystAnswer
        judge the answer against its criteria + ground truth
    aggregate -> pass rate overall + per category
    print a pass table and the failures (with reasons — that's where the work is)
    exit non-zero when the overall pass rate drops below MIN_PASS_RATE (for CI).

Run:
    python -m project.eval.run

This module is the only one in the package that calls the agent / LLM / DB — the
dataset and judge are pure libraries.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass

from project.agents import ask
from project.schemas import AnalystAnswer
from project.tools.sql import run_sql
from project.eval.dataset import CASES, EvalCase
from project.eval.judge import Judgement, judge

# Minimum overall pass rate for the run to be considered green (used by CI).
MIN_PASS_RATE = 0.80


def compute_ground_truth(case: EvalCase) -> str | None:
    """Run `case.expected_sql` (read-only) and return the rendered result, or None.

    Returns None when the case has no expected_sql. On a SQL error we still return the
    string (it starts with 'SQLError'/'Refused') so the runner surfaces it rather than
    silently dropping the reference; the judge then falls back to `case.expected`.
    """
    if not case.expected_sql:
        return None
    return run_sql(case.expected_sql)


@dataclass
class Result:
    case: EvalCase
    answer: AnalystAnswer
    ground_truth: str | None
    judgement: Judgement


def run_all(cases: list[EvalCase] = CASES) -> list[Result]:
    """Run every case end-to-end: ground truth -> agent -> judge. Returns Results."""
    results: list[Result] = []
    for case in cases:
        gt = compute_ground_truth(case)
        # Don't pass a SQL error string in as authoritative "ground truth".
        gt_for_judge = gt if (gt and not gt.startswith(("SQLError", "Refused"))) else None
        if gt and gt_for_judge is None:
            print(f"  ! {case.id}: ground-truth SQL failed: {gt[:120]}", file=sys.stderr)

        answer = ask(case.question)
        j = judge(case, answer, ground_truth=gt_for_judge)
        results.append(Result(case=case, answer=answer, ground_truth=gt, judgement=j))
    return results


def report(results: list[Result]) -> float:
    """Print an aggregate pass table + every failure's reason. Returns overall pass rate."""
    if not results:
        print("No results.")
        return 0.0

    cat_total: dict[str, int] = defaultdict(int)
    cat_passed: dict[str, int] = defaultdict(int)
    for r in results:
        cat_total[r.case.category] += 1
        if r.judgement.passed:
            cat_passed[r.case.category] += 1

    passed = sum(1 for r in results if r.judgement.passed)
    overall = passed / len(results)

    print(f"\nOverall: {passed}/{len(results)} passed ({overall:.0%})\n")
    print("By category:")
    for cat in sorted(cat_total):
        c_pass, c_tot = cat_passed[cat], cat_total[cat]
        print(f"  {cat:<14} {c_pass}/{c_tot} ({c_pass / c_tot:.0%})")

    failures_by_cat: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        if not r.judgement.passed:
            failures_by_cat[r.case.category].append(r)

    if not failures_by_cat:
        print("\nNo failures. (Read the reasons anyway — a clean run can hide weak criteria.)")
        return overall

    print("\nFailures (largest cluster first):")
    for cat in sorted(failures_by_cat, key=lambda c: len(failures_by_cat[c]), reverse=True):
        rs = failures_by_cat[cat]
        print(f"\n  {cat} — {len(rs)} failing:")
        for r in rs:
            print(f"    [{r.case.id}] score={r.judgement.score:.2f}")
            print(f"        reason: {r.judgement.reason}")

    return overall


def main() -> int:
    overall = report(run_all())
    print(f"\nThreshold: {MIN_PASS_RATE:.0%} — {'PASS' if overall >= MIN_PASS_RATE else 'FAIL'}")
    return 0 if overall >= MIN_PASS_RATE else 1


if __name__ == "__main__":
    sys.exit(main())
