"""Anomaly detection — runs the dialect-portable checks against the SQLite warehouse.

Guards against regressions in the Watch capability: the planted, currently-true stories (West
conversion drop, Rivet returns, flashdeal churn) must surface, and every anomaly is well-formed.
"""

from __future__ import annotations

from project.tools.anomalies import detect_anomalies


def test_surfaces_the_planted_stories():
    metrics = [a.metric.lower() for a in detect_anomalies()]
    assert any("conversion" in m for m in metrics), "West conversion drop should surface"
    assert any("return rate" in m for m in metrics), "Rivet/Bottoms returns should surface"
    assert any("repeat" in m for m in metrics), "flashdeal repeat-rate should surface"


def test_every_anomaly_is_well_formed():
    found = detect_anomalies()
    assert found
    for a in found:
        assert a.severity in {"low", "medium", "high"}
        assert a.finding and a.evidence and a.recommendation
