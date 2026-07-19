"""Dashboard data: KPIs and chart series for the Streamlit Workbench.

Pure, read-only aggregates over the warehouse (no LLM, no forecast). Backend-agnostic: month
extraction adapts to SQLite vs BigQuery; the rest is portable SQL. Returns plain dicts/lists so
the UI just renders st.metric + st.*_chart. Every query is defensive (an error becomes an empty
series), so the dashboard degrades gracefully instead of crashing.
"""

from __future__ import annotations

from project.config import USE_BIGQUERY
from project.tools.sql import query_table


def _ym(col: str) -> str:
    """Dialect-aware 'YYYY-MM' month bucket for a timestamp column."""
    return f"FORMAT_TIMESTAMP('%Y-%m', {col})" if USE_BIGQUERY else f"substr({col}, 1, 7)"


def _rows(sql: str) -> list[dict]:
    """Run a read-only query and return list[dict]; [] on any error."""
    res = query_table(sql)
    if isinstance(res, str):  # error string from the SQL layer
        return []
    rows, cols = res
    return [dict(zip(cols, r)) for r in rows]


def _last_two(values: list):
    vals = [v for v in values if v is not None]
    return (vals[-1] if vals else None), (vals[-2] if len(vals) >= 2 else None)


def dashboard_data() -> dict:
    """Return {'kpis': [...], 'charts': {...}} for the Workbench dashboard."""
    rev = _rows(
        f"SELECT {_ym('order_ts')} AS month, ROUND(SUM(subtotal - discount), 2) AS net_revenue, "
        "COUNT(*) AS orders FROM orders WHERE status='completed' GROUP BY month ORDER BY month"
    )
    gm = _rows(
        f"SELECT {_ym('o.order_ts')} AS month, "
        "ROUND(100.0 * SUM(oi.line_revenue - oi.line_cost) / NULLIF(SUM(oi.line_revenue), 0), 1) AS gross_margin "
        "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
        "WHERE o.status='completed' GROUP BY month ORDER BY month"
    )
    conv = _rows(
        f"SELECT {_ym('session_ts')} AS month, ROUND(AVG(converted), 4) AS conv "
        "FROM web_sessions GROUP BY month ORDER BY month"
    )
    ret = _rows(f"SELECT {_ym('return_ts')} AS month, COUNT(*) AS returns FROM returns GROUP BY month ORDER BY month")

    # ── KPIs: latest full month vs the prior month ───────────────────
    kpis: list[dict] = []

    rev_cur, rev_prev = _last_two([r["net_revenue"] for r in rev])
    if rev_cur is not None:
        kpis.append({"label": "Net revenue (last mo)", "value": f"${rev_cur:,.0f}",
                     "delta": (f"${rev_cur - rev_prev:+,.0f}" if rev_prev is not None else None)})

    ord_cur, ord_prev = _last_two([r["orders"] for r in rev])
    if ord_cur is not None:
        kpis.append({"label": "Orders (last mo)", "value": f"{ord_cur:,}",
                     "delta": (f"{ord_cur - ord_prev:+,}" if ord_prev is not None else None)})

    if rev_cur and ord_cur:
        aov_cur = rev_cur / ord_cur
        aov_prev = (rev_prev / ord_prev) if (rev_prev and ord_prev) else None
        kpis.append({"label": "AOV (last mo)", "value": f"${aov_cur:,.0f}",
                     "delta": (f"${aov_cur - aov_prev:+,.0f}" if aov_prev else None)})

    gm_cur, gm_prev = _last_two([r["gross_margin"] for r in gm])
    if gm_cur is not None:
        kpis.append({"label": "Gross margin", "value": f"{gm_cur:.1f}%",
                     "delta": (f"{gm_cur - gm_prev:+.1f} pts" if gm_prev is not None else None)})

    cv_cur, cv_prev = _last_two([r["conv"] for r in conv])
    if cv_cur is not None:
        kpis.append({"label": "Conversion (last mo)", "value": f"{cv_cur * 100:.2f}%",
                     "delta": (f"{(cv_cur - cv_prev) * 100:+.2f} pts" if cv_prev is not None else None)})

    if rev and ret:
        orders_by_m = {r["month"]: r["orders"] for r in rev}
        returns_by_m = {r["month"]: r["returns"] for r in ret}
        months = [r["month"] for r in rev]

        def _rrate(m):
            return (returns_by_m.get(m, 0) / orders_by_m[m]) if orders_by_m.get(m) else None

        rr_cur = _rrate(months[-1]) if months else None
        rr_prev = _rrate(months[-2]) if len(months) >= 2 else None
        if rr_cur is not None:
            kpis.append({"label": "Return rate (last mo)", "value": f"{rr_cur * 100:.1f}%",
                         "delta": (f"{(rr_cur - rr_prev) * 100:+.1f} pts" if rr_prev is not None else None)})

    # ── Chart series ─────────────────────────────────────────────────
    charts = {
        "revenue_by_month": [{"month": r["month"], "net_revenue": r["net_revenue"]} for r in rev],
        "conversion_by_month": [{"month": r["month"], "conversion_%": round((r["conv"] or 0) * 100, 2)} for r in conv],
        "revenue_by_category": _rows(
            "SELECT p.category AS category, ROUND(SUM(oi.line_revenue), 2) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status='completed' GROUP BY category ORDER BY revenue DESC"
        ),
        "revenue_by_region": _rows(
            "SELECT ship_region AS region, ROUND(SUM(subtotal - discount), 2) AS net_revenue "
            "FROM orders WHERE status='completed' GROUP BY region ORDER BY net_revenue DESC"
        ),
        "return_rate_by_subcategory": _rows(
            "SELECT p.subcategory AS subcategory, "
            "ROUND(100.0 * COUNT(DISTINCT r.return_id) / NULLIF(COUNT(DISTINCT oi.order_item_id), 0), 1) AS return_rate_pct "
            "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
            "LEFT JOIN returns r ON r.order_item_id = oi.order_item_id "
            "GROUP BY subcategory HAVING COUNT(DISTINCT oi.order_item_id) >= 30 "
            "ORDER BY return_rate_pct DESC LIMIT 8"
        ),
        "top_products": _rows(
            "SELECT p.name AS product, ROUND(SUM(oi.line_revenue), 2) AS revenue "
            "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
            "JOIN products p ON p.product_id = oi.product_id "
            "WHERE o.status='completed' GROUP BY product ORDER BY revenue DESC LIMIT 8"
        ),
        "marketing_spend_by_channel": _rows(
            "SELECT channel, ROUND(SUM(spend), 0) AS spend FROM marketing_campaigns "
            "GROUP BY channel ORDER BY spend DESC"
        ),
    }
    return {"kpis": kpis, "charts": charts}


if __name__ == "__main__":
    d = dashboard_data()
    print("KPIs:")
    for k in d["kpis"]:
        print(f"  {k['label']:24} {k['value']:>14}  ({k['delta']})")
    print("\nChart series (rows):")
    for name, rows in d["charts"].items():
        print(f"  {name:30} {len(rows)}")
