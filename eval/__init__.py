"""Evaluation harness for the Loom & Co. BI Analyst Agent.

Public surface:
    CASES, EvalCase   — the eval dataset (factual / citation / hallucination).
    judge, Judgement  — LLM-as-judge with per-category rubrics.
    run_all, report   — execute + score all cases (the runner; see `python -m project.eval.run`).

Importing this package has no side effects — no DB, LLM, or network calls happen
until `run_all()` / `judge()` are invoked.
"""

from __future__ import annotations

from project.eval.dataset import CASES, EvalCase
from project.eval.judge import Judgement, judge
from project.eval.run import MIN_PASS_RATE, compute_ground_truth, report, run_all

__all__ = [
    "CASES",
    "EvalCase",
    "Judgement",
    "judge",
    "run_all",
    "report",
    "compute_ground_truth",
    "MIN_PASS_RATE",
]
