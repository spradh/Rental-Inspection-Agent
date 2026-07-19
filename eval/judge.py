"""LLM-as-judge — rubric-based scoring on top of shared.llm.

The judge reads (case, agent answer, optional computed ground truth) and returns a
structured Judgement. Two habits keep it honest:
    1. ask for the REASON before the score (reason-then-score reduces rationalizing).
    2. return a structured object so the runner can aggregate without parsing prose.

The judge is not infallible — validate it against a small human-labeled set and watch
for verbosity / position / self-preference bias.

This is a LIBRARY: importing it makes no LLM/network call. `judge()` calls the LLM
only when invoked (by run.py).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from shared.llm import chat
from project.schemas import AnalystAnswer
from project.eval.dataset import EvalCase

# A strong, cheap-ish judge. Kept distinct from the agent's own models so the judge
# isn't grading purely by self-preference.
JUDGE_MODEL = "anthropic:claude-sonnet-4-6"

# Score at or above this is a pass when the model doesn't return an explicit `passed`.
PASS_THRESHOLD = 0.7


class Judgement(BaseModel):
    """The judge's verdict on one (case, answer) pair."""

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str


# Per-category rubric. Keep these tight — the rubric IS the spec.
RUBRICS: dict[str, str] = {
    "factual": (
        "Score how factually correct the answer is for Loom & Co. 1.0 = the key "
        "figure/fact is correct and consistent with the reference (within stated "
        "tolerance); 0.0 = the key claim is wrong. A correct number missing a required "
        "qualifier (period, region, unit) is a partial answer (~0.5), not a pass. "
        "Trust the COMPUTED GROUND TRUTH over the agent when they disagree."
    ),
    "citation": (
        "Score citation quality. 1.0 = the claim is correct AND attributed to a real, "
        "relevant Loom & Co. source (a metric definition, the data dictionary, the Q1 "
        "business review, the data-access policy, or the warehouse tables) that actually "
        "supports it; 0.0 = the claim is uncited or the cited source does not support "
        "it. A factually correct answer with NO source must score low — being right is "
        "not enough. Invented or mismatched sources score 0.0."
    ),
    "hallucination": (
        "Score whether the answer avoids hallucination on a false/unknowable premise. "
        "1.0 = it refuses, flags the bad premise, or says it has no data; 0.0 = it "
        "invents facts, figures, dates, or sources. Confident, fluent invention is the "
        "worst outcome — score it 0.0. Offering a real, applicable alternative while "
        "declining the bad premise is still a pass."
    ),
}

JUDGE_SYSTEM = """You are a strict, fair evaluator of a business-intelligence agent's \
answers for Loom & Co. (an apparel retailer). Apply ONLY the rubric and criteria \
given. Be skeptical of confident, fluent answers — fluency is not correctness. \
Penalize uncited or invented facts heavily. When a computed ground truth is provided, \
treat it as authoritative.

Respond with EXACTLY ONE json object, no prose, no code fences:
  {"reason": "<1-3 sentences, written BEFORE deciding the score>",
   "score": <float 0.0-1.0>,
   "passed": <true|false>}
"""


def _answer_text(answer: AnalystAnswer) -> str:
    """Render the structured answer into a single block the judge can read.

    We include evidence, citations, SQL and confidence so citation-quality cases can be
    judged on what the agent actually cited (the `citations` field), not just prose.
    """
    parts: list[str] = [f"answer: {answer.answer}"]
    if answer.evidence:
        parts.append("evidence:\n" + "\n".join(f"  - {e}" for e in answer.evidence))
    if answer.recommendations:
        parts.append(
            "recommendations:\n" + "\n".join(f"  - {r}" for r in answer.recommendations)
        )
    if answer.citations:
        parts.append("citations:\n" + "\n".join(f"  - {c}" for c in answer.citations))
    if answer.sql_used:
        parts.append("sql_used:\n" + "\n".join(f"  - {s}" for s in answer.sql_used))
    parts.append(f"confidence: {answer.confidence}")
    return "\n".join(parts)


def _parse_judgement(raw: str) -> dict:
    """Parse the judge's JSON, tolerating code fences / surrounding prose."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object in judge output: {raw!r}")
        return json.loads(match.group(0))


def judge(
    case: EvalCase,
    answer: AnalystAnswer,
    *,
    ground_truth: str | None = None,
) -> Judgement:
    """Score one agent answer against its case. Returns a structured Judgement.

    `ground_truth` is the value computed by run.py from `case.expected_sql` (preferred);
    we fall back to the static `case.expected` when no SQL ground truth was computed.
    """
    rubric = RUBRICS.get(case.category)
    if rubric is None:
        raise ValueError(f"No rubric for category {case.category!r} (case {case.id})")

    reference = ground_truth if ground_truth is not None else case.expected
    ref_block = f"\nComputed ground truth (authoritative):\n{reference}\n" if reference else ""

    user = f"""Rubric: {rubric}

Question:
{case.question}

Criteria a passing answer must satisfy:
{case.criteria}{ref_block}
Agent answer to evaluate:
{_answer_text(answer)}
"""
    raw = chat(user, system=JUDGE_SYSTEM, model=JUDGE_MODEL, temperature=0.0)
    obj = _parse_judgement(raw)
    score = float(obj["score"])
    return Judgement(
        score=score,
        passed=bool(obj.get("passed", score >= PASS_THRESHOLD)),
        reason=str(obj.get("reason", "")),
    )


__all__ = ["Judgement", "judge", "JUDGE_MODEL", "PASS_THRESHOLD", "RUBRICS"]
