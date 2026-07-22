"""Unit tests for the tool registry — runs against the real SQLite warehouse (offline).

These prove every tool the agent can call produces an output (a non-error string) for a
valid call, and that dispatch turns bad input into observations instead of crashing.
"""

from __future__ import annotations

import pytest

from project.tools import REGISTRY, dispatch, get_tools, tool_schemas

# (tool name, valid args) — one happy-path call per tool the specialists rely on.
HAPPY_PATHS = [
    ("run_sql", {"sql": "SELECT COUNT(*) AS n FROM orders"}),
    ("get_schema", {}),
    ("lookup_metric", {"name": "Net revenue"}),
    ("web_analytics", {"metric": "conversion", "region": "West"}),
    ("forecast_net_revenue", {}),
]


def _is_error(s: str, name: str) -> bool:
    low = s.lower()
    return low.startswith("dispatch error") or low.startswith(f"{name} error")


@pytest.mark.parametrize("name,args", HAPPY_PATHS)
def test_dispatch_produces_output(name, args):
    if name not in REGISTRY:
        pytest.skip(f"{name} not registered")
    result = dispatch(name, args)
    assert isinstance(result, str) and result.strip(), f"{name} returned empty"
    assert not _is_error(result, name), f"{name} unexpectedly errored: {result[:200]}"


def test_run_sql_refuses_writes():
    result = dispatch("run_sql", {"sql": "DROP TABLE orders"})
    assert "refused" in result.lower()  # write blocked -> observation, not a crash


def test_dispatch_unknown_tool_is_an_observation():
    result = dispatch("does_not_exist", {})
    assert result.lower().startswith("dispatch error")
    assert "unknown tool" in result.lower()


def test_dispatch_invalid_args_is_an_observation():
    # run_sql requires `sql`; omitting it must yield a validation observation, not raise.
    result = dispatch("run_sql", {})
    assert "invalid args" in result.lower()


def test_dispatch_never_raises_on_bad_args_type():
    assert isinstance(dispatch("run_sql", "not-a-dict"), str)  # type: ignore[arg-type]


def test_tool_schemas_shape_and_subset():
    all_schemas = tool_schemas()
    assert all_schemas and all({"name", "description", "input_schema"} <= set(s) for s in all_schemas)
    subset = tool_schemas(["run_sql"])
    assert [s["name"] for s in subset] == ["run_sql"]


def test_get_tools_filters_known_names():
    specs = get_tools(["run_sql", "lookup_metric", "nope"])
    names = {s.name for s in specs}
    assert names == {"run_sql", "lookup_metric"}  # unknown silently skipped
