"""Opt-in LIVE integration tests — calls the REAL model across many task types.

Skipped by default. Enable with a real provider key configured (see .env) and:

    RUN_LLM_TESTS=1 uv run pytest project/tests/test_agents_live.py -v

These prove the genuine end-to-end claim: invoking the agent across factual, citation, and
hallucination-adversarial tasks generates a well-formed AnalystAnswer each time. The suite
runs on the SQLite warehouse (conftest forces it), so it never depends on BigQuery/ADC.
"""

from __future__ import annotations

import os

import pytest

from project.agents import ask
from project.eval.dataset import CITATION, FACTUAL, HALLUCINATION
from project.schemas import AnalystAnswer

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LLM_TESTS") != "1", reason="set RUN_LLM_TESTS=1 to run live model tests"
)

# A spread across all three eval categories — "various tasks".
LIVE_TASKS = [
    pytest.param(FACTUAL[0].question, id="factual"),
    pytest.param(CITATION[0].question, id="citation"),
    pytest.param(HALLUCINATION[0].question, id="hallucination"),
]


@pytest.mark.parametrize("question", LIVE_TASKS)
def test_live_ask_generates_output(question):
    result = ask(question)
    assert isinstance(result, AnalystAnswer)
    assert result.answer.strip(), "live model produced an empty answer"
    assert 0.0 <= result.confidence <= 1.0
