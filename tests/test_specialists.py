"""Unit tests for Specialist.run — the native tool-calling specialist (LLM seam mocked)."""

from __future__ import annotations

import json

import project.agents.specialists as sp


def test_roster_and_menu():
    assert set(sp.SPECIALISTS) == {"sales", "marketing", "product", "forecasting"}
    assert sp.specialist_menu().strip()


def test_run_appends_executed_sql_and_injects_schema(monkeypatch):
    captured = {}

    def fake(**kw):
        captured.update(kw)
        return ("March net revenue is $113,732.02.", [{"name": "run_sql", "args": {"sql": "SELECT 1"}, "result": "1"}])

    monkeypatch.setattr(sp, "run_tool_loop", fake)
    out, chart = sp.SPECIALISTS["sales"].run("What was March net revenue?")

    assert "113,732.02" in out
    assert "SQL run:" in out and "SELECT 1" in out          # faithful provenance appended
    assert "Warehouse schema" in captured["system"]          # injected for an SQL specialist
    assert "plot" in captured["system"].lower()              # charting hint injected (sales has plot)
    assert chart is None                                      # no plot call -> no chart


def test_run_captures_chart_from_plot_call(monkeypatch):
    spec = {"type": "line", "title": "Net revenue", "x": ["2026-01", "2026-02"],
            "series": [{"name": "net_revenue", "values": [100.0, 120.0]}]}

    def fake(**kw):
        return ("Revenue is trending up.", [{"name": "plot", "args": {"sql": "SELECT ..."}, "result": json.dumps(spec)}])

    monkeypatch.setattr(sp, "run_tool_loop", fake)
    _text, chart = sp.SPECIALISTS["sales"].run("Plot net revenue by month")

    assert chart == spec  # the ChartSpec JSON from the plot tool is captured as a dict


def test_run_ignores_failed_plot(monkeypatch):
    def fake(**kw):
        return ("ok", [{"name": "plot", "args": {}, "result": "PlotError: need ≥2 columns"}])

    monkeypatch.setattr(sp, "run_tool_loop", fake)
    _text, chart = sp.SPECIALISTS["sales"].run("Plot something invalid")

    assert chart is None  # an error string doesn't parse as JSON -> no chart


def test_non_sql_specialist_gets_no_schema_and_empty_falls_back(monkeypatch):
    captured = {}

    def fake(**kw):
        captured.update(kw)
        return ("", [])  # model produced nothing

    monkeypatch.setattr(sp, "run_tool_loop", fake)
    out, chart = sp.SPECIALISTS["forecasting"].run("Project revenue")

    assert out == "(no findings)"                             # empty text -> safe fallback
    assert chart is None
    assert "Warehouse schema" not in captured["system"]       # forecasting has no run_sql
