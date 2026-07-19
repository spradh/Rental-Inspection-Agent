"""Unit tests for dashboard_data — aggregates over the real SQLite warehouse (offline)."""

from __future__ import annotations

from project.dashboard import dashboard_data

_EXPECTED_CHARTS = {
    "revenue_by_month",
    "conversion_by_month",
    "revenue_by_category",
    "revenue_by_region",
    "return_rate_by_subcategory",
    "top_products",
    "marketing_spend_by_channel",
}


def test_kpis_present_and_formatted():
    d = dashboard_data()
    assert d["kpis"], "expected at least some KPIs"
    for k in d["kpis"]:
        assert k["label"] and k["value"]  # delta may be None on the first month
    labels = {k["label"] for k in d["kpis"]}
    assert any("Net revenue" in lbl for lbl in labels)


def test_all_chart_series_present_and_populated():
    charts = dashboard_data()["charts"]
    assert _EXPECTED_CHARTS <= set(charts)
    # Core trend series populated with the expected fields.
    rev = charts["revenue_by_month"]
    assert rev and all("month" in r and "net_revenue" in r for r in rev)
    assert charts["revenue_by_category"]
    assert charts["revenue_by_region"]
    assert all(isinstance(r["net_revenue"], (int, float)) for r in charts["revenue_by_region"])
