"""Shared pytest fixtures for the BI Analyst Agent unit tests.

Design goals for the default suite:
  * OFFLINE & DETERMINISTIC — no network, no API key, no BigQuery. We force the SQLite
    warehouse and mock the LLM layer, so `pytest` runs anywhere in <1s and never flakes.
  * The agent graph is still exercised END-TO-END — supervisor routing, a specialist tool
    loop, synthesis, and provenance backfill all run; only the model calls are faked.

A second, OPT-IN tier (test_agents_live.py) calls the real model across many task types to
prove that real outputs are generated — run it with `RUN_LLM_TESTS=1 uv run pytest`.

IMPORTANT: the env overrides below MUST run before any `project.*` import, because
`project.config` reads the environment once at import time. Keep them at the very top.
"""

from __future__ import annotations

import os

# Force the local SQLite warehouse (empty BIGQUERY_PROJECT -> USE_BIGQUERY=False) so tools
# never touch BigQuery/ADC during tests. Must be set BEFORE project.config reads the env;
# config's load_dotenv(override=False) then won't clobber it.
os.environ["BIGQUERY_PROJECT"] = ""

# Import config now so it loads .env (populating REAL provider keys, which the opt-in live
# tier needs). Only AFTER that do we add dummy fallbacks for CI machines without a .env.
from project.config import DB_PATH  # noqa: E402

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

import json  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _require_warehouse():
    """Skip the whole suite cleanly if the SQLite warehouse hasn't been generated."""
    if not DB_PATH.exists():
        pytest.skip(f"warehouse missing: {DB_PATH} (run: python -m data.generate)", allow_module_level=True)


# A valid AnalystAnswer JSON the fake synthesis step returns — note sql_used/citations are
# intentionally empty so tests can prove the graph BACKFILLS provenance from tool output.
FAKE_ANSWER_JSON = json.dumps(
    {
        "answer": "Net revenue in March 2026 was $113,732.02, from completed orders (subtotal - discount).",
        "evidence": ["completed orders only", "subtotal minus discount"],
        "recommendations": ["Track West-region conversion weekly."],
        "sql_used": [],
        "citations": [],
        "confidence": 0.9,
    }
)

# What the fake specialist tool loop "executed": one real-looking run_sql call. The graph's
# _extract_sql should lift this into AnalystAnswer.sql_used.
FAKE_SQL = "SELECT SUM(subtotal) - SUM(discount) FROM orders WHERE status = 'completed'"

# A ChartSpec the fake `plot` call returns — the graph should attach it to AnalystAnswer.chart.
FAKE_CHART = {
    "type": "line",
    "title": "Net revenue by month",
    "x_label": "month",
    "y_label": "net_revenue",
    "x": ["2026-01", "2026-02", "2026-03"],
    "series": [{"name": "net_revenue", "values": [100.0, 110.0, 113.7]}],
}


def _make_fake_chat():
    """A stateful stand-in for shared.llm.chat used by supervisor + synthesis.

    Routes to exactly one specialist (so the specialist node runs), then to synthesis, then
    returns a valid AnalystAnswer JSON. Branches purely on prompt content.
    """
    state = {"routed": False}

    def fake_chat(prompt, model=None, system=None):
        if "route key" in prompt.lower():  # supervisor routing prompt
            if not state["routed"]:
                state["routed"] = True
                return "sales"
            return "synthesize"
        return FAKE_ANSWER_JSON  # synthesis prompt

    return fake_chat


def _fake_run_tool_loop(*, model, system, user, tools, execute, max_steps=6, max_tokens=1024):
    """Stand-in for shared.llm.run_tool_loop: returns findings + a run_sql call + a plot call."""
    calls = [
        {"name": "run_sql", "args": {"sql": FAKE_SQL}, "result": "113732.02"},
        {"name": "plot", "args": {"sql": "SELECT month, net_revenue FROM …"}, "result": json.dumps(FAKE_CHART)},
    ]
    return ("March 2026 net revenue is $113,732.02.", calls)


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the agent's two LLM seams so ask()/the graph run fully offline & deterministically."""
    import project.agents.graph as graph
    import project.agents.specialists as specialists

    monkeypatch.setattr(graph, "chat", _make_fake_chat())
    monkeypatch.setattr(specialists, "run_tool_loop", _fake_run_tool_loop)
    return None
