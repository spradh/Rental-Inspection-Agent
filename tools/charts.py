"""Charting tool — turn a SQL result into a render-agnostic ChartSpec.

The model asks for a chart by calling `plot()` with a SELECT whose FIRST column is the x-axis
(labels) and whose remaining NUMERIC columns are the series. We run that SQL and build the
spec from the REAL rows, so the chart's numbers are grounded in the warehouse — never invented
by the model. The spec is returned as JSON so it flows through the agent loop and the API, and
the UI renders it (Streamlit st.bar_chart / line_chart / area_chart).

This is the "Visualize" capability: the agent decides a chart helps, writes the SQL for the
data, and we draw it; the prose answer and the chart render together.
"""

from __future__ import annotations

from project.schemas import ChartSeries, ChartSpec
from project.tools.sql import query_table

_MAX_POINTS = 100  # bound chart size (and the observation handed back to the agent)


def plot(sql: str, chart_type: str = "bar", title: str = "") -> str:
    """Build a chart from a SELECT. Returns a ChartSpec as JSON, or a 'PlotError: …' string.

    Contract for `sql`: first column = x-axis labels; every remaining column that is numeric
    becomes a series. Example:
        SELECT substr(order_ts,1,7) AS month, SUM(subtotal - discount) AS net_revenue
        FROM orders WHERE status='completed' GROUP BY month ORDER BY month
    """
    result = query_table(sql)
    if isinstance(result, str):  # an error string from the SQL layer (guard / failure)
        return f"PlotError: {result}"
    rows, cols = result
    if not rows:
        return "PlotError: the query returned no rows to chart."
    if len(cols) < 2:
        return "PlotError: need ≥2 columns — first = x-axis labels, the rest = numeric series."

    rows = rows[:_MAX_POINTS]
    x = [str(r[0]) for r in rows]

    series: list[ChartSeries] = []
    for j in range(1, len(cols)):
        values: list[float] = []
        numeric = True
        for r in rows:
            try:
                values.append(float(r[j]))
            except (TypeError, ValueError):
                numeric = False
                break
        if numeric:
            series.append(ChartSeries(name=str(cols[j]), values=values))

    if not series:
        return "PlotError: no numeric column to plot (columns after the first must be numbers)."

    spec = ChartSpec(
        type=chart_type if chart_type in ("bar", "line", "area") else "bar",
        title=title or "",
        x_label=str(cols[0]),
        y_label=series[0].name if len(series) == 1 else "",
        x=x,
        series=series,
    )
    return spec.model_dump_json()


if __name__ == "__main__":
    demo = plot(
        "SELECT substr(order_ts,1,7) AS month, ROUND(SUM(subtotal - discount), 2) AS net_revenue "
        "FROM orders WHERE status='completed' GROUP BY month ORDER BY month LIMIT 6",
        chart_type="line",
        title="Net revenue by month",
    )
    print(demo)
