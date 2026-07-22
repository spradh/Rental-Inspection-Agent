"""Unit tests for the plot tool — runs against the real SQLite warehouse (offline).

The chart is built from REAL query rows, so these assert the spec is grounded in the data and
that bad inputs become 'PlotError: …' observations rather than crashes.
"""

from __future__ import annotations

import json

from project.tools.charts import plot


def test_plot_builds_spec_from_real_rows():
    out = plot(
        "SELECT substr(order_ts,1,7) AS month, ROUND(SUM(subtotal - discount), 2) AS net_revenue "
        "FROM orders WHERE status='completed' GROUP BY month ORDER BY month LIMIT 4",
        chart_type="line",
        title="Revenue",
    )
    spec = json.loads(out)
    assert spec["type"] == "line"
    assert spec["title"] == "Revenue"
    assert spec["x_label"] == "month"
    assert len(spec["x"]) == 4
    assert spec["series"][0]["name"] == "net_revenue"
    assert len(spec["series"][0]["values"]) == 4
    assert all(isinstance(v, (int, float)) for v in spec["series"][0]["values"])


def test_plot_refuses_non_select():
    assert plot("DROP TABLE orders").startswith("PlotError")


def test_plot_needs_at_least_two_columns():
    assert "2 columns" in plot("SELECT region FROM customers LIMIT 3")


def test_plot_needs_a_numeric_series():
    # Two columns, but the second is text -> no series to plot.
    out = plot("SELECT customer_id, first_name FROM customers LIMIT 3")
    assert out.startswith("PlotError")


def test_plot_invalid_chart_type_falls_back_to_bar():
    out = plot("SELECT region, COUNT(*) AS n FROM customers GROUP BY region", chart_type="pie")
    assert json.loads(out)["type"] == "bar"
