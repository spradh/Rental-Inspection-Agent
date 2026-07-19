"""Tests for the Report capability (weekly review)."""

from __future__ import annotations

import project.agents.report as report
from project.agents import weekly_review_data


def test_weekly_review_data_is_offline_and_populated():
    """No LLM: pulls anomalies + forecast straight from the warehouse/model."""
    data = weekly_review_data()
    assert {"anomalies", "forecast", "forecast_months"} <= set(data)
    assert isinstance(data["anomalies"], list)
    assert isinstance(data["forecast"], list) and data["forecast"], "forecast points generated"
    assert isinstance(data["forecast_months"], int) and data["forecast_months"] >= 1


def test_generate_report_produces_narrative(monkeypatch):
    monkeypatch.setattr(report, "chat", lambda *a, **k: "# Weekly Review\n\nHeadline: revenue up.")
    out = report.generate_report()
    assert isinstance(out, str) and out.strip().startswith("#")


def test_generate_report_unwraps_markdown_code_fence(monkeypatch):
    # Models often wrap the whole report in a ```markdown ... ``` fence — it must be stripped
    # so st.markdown renders the Markdown instead of a literal code block.
    fenced = "```markdown\n# Loom & Co. Weekly BI Review\n\n## Headline\nUp 12%.\n```"
    monkeypatch.setattr(report, "chat", lambda *a, **k: fenced)
    out = report.generate_report()
    assert out.startswith("# Loom & Co.")
    assert "```" not in out


def test_strip_code_fences_leaves_unfenced_text_untouched():
    md = "# Title\n\nbody **bold**"
    assert report._strip_code_fences(md) == md
