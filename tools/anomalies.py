"""Anomaly detection — the Watch capability.

Deterministic SQL checks that surface the KPI deviations leadership recurringly asks
about (the planted "Loom stories" — see data/docs/business-glossary.md → Known
watch-items):

  1. Margin dip            — gross margin % below its recent baseline (SPRING26 effect).
  2. West conversion drop  — West web conversion below its recent baseline.
  3. High-return subcat    — a subcategory with an outlier unit return rate (Rivet jeans).
  4. Low repeat-rate chan  — an acquisition channel with weak repeat-purchase (flashdeal).

Temporal checks (1, 2) compare the latest month against a TRAILING baseline (recent months),
so a sustained drop still surfaces instead of looking normal once it plateaus; checks (3, 4)
compare the worst segment against the overall rate. Queries are dialect-portable (SQLite +
BigQuery). All checks are defensive: any failure is skipped, so one bad query can't sink the
run.

Demo:
    python -m project.tools.anomalies
"""

from __future__ import annotations

from project.config import USE_BIGQUERY
from project.schemas import Anomaly
from project.tools.sql import query_rows


def _ym(col: str) -> str:
    """Dialect-aware 'YYYY-MM' month bucket (BigQuery TIMESTAMP vs SQLite TEXT)."""
    return f"FORMAT_TIMESTAMP('%Y-%m', {col})" if USE_BIGQUERY else f"substr({col}, 1, 7)"


def _mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _rows(sql: str):
    """Run a query, returning rows or None on any error/empty result."""
    res = query_rows(sql)
    if isinstance(res, str) or not res:
        return None
    return res


def _check_margin_dip() -> Anomaly | None:
    """Gross margin % by month; flag if the latest month is below its recent baseline."""
    rows = _rows(
        f"""
        WITH rev AS (
          SELECT {_ym('order_ts')} AS ym, SUM(subtotal - discount) AS net
          FROM orders WHERE status = 'completed' GROUP BY ym
        ),
        cost AS (
          SELECT {_ym('o.order_ts')} AS ym, SUM(oi.line_cost) AS cogs
          FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
          WHERE o.status = 'completed' GROUP BY ym
        )
        SELECT rev.ym, rev.net, cost.cogs
        FROM rev JOIN cost ON cost.ym = rev.ym
        WHERE rev.net > 0 ORDER BY rev.ym
        """
    )
    if not rows or len(rows) < 3:
        return None
    margins = [((net - cogs) / net if net and cogs is not None else None) for _ym_, net, cogs in rows]
    cur_ym, cur_net, _cur_cogs = rows[-1]
    cur_m = margins[-1]
    base = _mean(margins[-7:-1])  # trailing up to 6 months before the latest
    if cur_m is None or base is None:
        return None
    delta = cur_m - base
    if delta >= -0.02:  # < 2pt below the recent baseline is noise
        return None
    sev = "high" if delta <= -0.05 else "medium"
    return Anomaly(
        metric="Gross margin %",
        finding=(
            f"Gross margin in {cur_ym} is {cur_m:.1%}, {delta:+.1%} pts below its recent "
            f"baseline of {base:.1%} — consistent with promo-driven discounting."
        ),
        severity=sev,
        evidence=f"{cur_ym}: net ${cur_net:,.0f}, margin {cur_m:.1%}; recent baseline {base:.1%}.",
        recommendation=(
            "Audit active promos (e.g. SPRING26): confirm the volume lift offsets the "
            "margin compression; consider tighter promo caps or exclusions on thin-margin SKUs."
        ),
    )


def _check_west_conversion() -> Anomaly | None:
    """West web conversion by month; flag if the latest month is below its recent baseline.

    Uses a trailing baseline (not just the prior month) so a sustained drop that's already
    'baked in' still surfaces, instead of looking normal once it plateaus.
    """
    rows = _rows(
        f"""
        SELECT {_ym('session_ts')} AS ym,
               AVG(converted)       AS conv,
               COUNT(*)             AS n
        FROM web_sessions
        WHERE LOWER(region) = 'west'
        GROUP BY ym
        HAVING COUNT(*) >= 20
        ORDER BY ym
        """
    )
    if not rows or len(rows) < 3:
        return None
    cur_ym, cur_conv, cur_n = rows[-1]
    base = _mean([conv for _ym_, conv, _n in rows[-7:-1]])  # trailing up to 6 months
    if cur_conv is None or not base:
        return None
    rel = (cur_conv - base) / base
    if rel >= -0.15:  # < 15% below the recent baseline is noise
        return None
    sev = "high" if rel <= -0.30 else "medium"
    return Anomaly(
        metric="West web conversion rate",
        finding=(
            f"West conversion in {cur_ym} is {cur_conv:.2%}, {rel:+.0%} vs its recent baseline "
            f"of {base:.2%} — a sustained regional funnel softening."
        ),
        severity=sev,
        evidence=f"{cur_ym}: {cur_conv:.2%} (n={cur_n}); recent baseline {base:.2%}.",
        recommendation=(
            "Investigate West-specific funnel friction (regional promo, shipping ETA, "
            "landing pages); compare add-to-cart vs checkout drop-off."
        ),
    )


def _check_return_subcategory() -> Anomaly | None:
    """Unit return rate by subcategory; flag the worst outlier vs the overall rate."""
    rows = _rows(
        """
        WITH sold AS (
          SELECT p.subcategory AS subcat, COUNT(*) AS units
          FROM order_items oi
          JOIN orders   o ON o.order_id = oi.order_id
          JOIN products p ON p.product_id = oi.product_id
          WHERE o.status = 'completed'
          GROUP BY p.subcategory
        ),
        ret AS (
          SELECT p.subcategory AS subcat, COUNT(*) AS rets
          FROM returns r
          JOIN products p ON p.product_id = r.product_id
          GROUP BY p.subcategory
        )
        SELECT sold.subcat,
               sold.units,
               COALESCE(ret.rets, 0)                       AS rets,
               1.0 * COALESCE(ret.rets, 0) / sold.units    AS rate
        FROM sold
        LEFT JOIN ret ON ret.subcat = sold.subcat
        WHERE sold.units >= 30
        ORDER BY rate DESC
        """
    )
    if not rows or len(rows) < 2:
        return None
    total_units = sum(r[1] for r in rows)
    total_rets = sum(r[2] for r in rows)
    overall = (total_rets / total_units) if total_units else 0.0
    subcat, units, rets, rate = rows[0]
    if overall <= 0 or rate < overall * 1.5:  # must be ~50%+ above baseline
        return None
    sev = "high" if rate >= overall * 2 else "medium"
    return Anomaly(
        metric="Return rate (units) by subcategory",
        finding=(
            f"'{subcat}' has the highest return rate at {rate:.1%}, "
            f"~{rate / overall:.1f}x the overall {overall:.1%}."
        ),
        severity=sev,
        evidence=f"'{subcat}': {rets} returns / {units} units sold = {rate:.1%}; overall {overall:.1%}.",
        recommendation=(
            "Drill into return reasons for this subcategory (likely fit). Review sizing "
            "guidance, fit imagery, and PDP measurements to reduce fit-driven returns."
        ),
    )


def _check_repeat_rate_channel() -> Anomaly | None:
    """Repeat-purchase rate by acquisition channel; flag the weakest vs overall."""
    rows = _rows(
        """
        WITH cust AS (
          SELECT c.acquisition_channel AS chan,
                 c.customer_id          AS cid,
                 COUNT(o.order_id)       AS n_orders
          FROM customers c
          JOIN orders o ON o.customer_id = c.customer_id AND o.status = 'completed'
          GROUP BY c.customer_id, c.acquisition_channel
        )
        SELECT chan,
               COUNT(*)                                          AS buyers,
               SUM(CASE WHEN n_orders >= 2 THEN 1 ELSE 0 END)    AS repeaters,
               1.0 * SUM(CASE WHEN n_orders >= 2 THEN 1 ELSE 0 END)
                 / COUNT(*)                                      AS repeat_rate
        FROM cust
        GROUP BY chan
        HAVING buyers >= 20
        ORDER BY repeat_rate ASC
        """
    )
    if not rows or len(rows) < 2:
        return None
    total_buyers = sum(r[1] for r in rows)
    total_rep = sum(r[2] for r in rows)
    overall = (total_rep / total_buyers) if total_buyers else 0.0
    chan, buyers, repeaters, rate = rows[0]
    if overall <= 0 or rate > overall * 0.7:  # must be clearly below baseline
        return None
    sev = "high" if rate <= overall * 0.5 else "medium"
    return Anomaly(
        metric="Repeat-purchase rate by acquisition channel",
        finding=(
            f"'{chan}'-acquired customers repeat least at {rate:.1%}, "
            f"vs {overall:.1%} overall — a loyalty/quality-of-traffic gap."
        ),
        severity=sev,
        evidence=f"'{chan}': {repeaters}/{buyers} buyers repeat = {rate:.1%}; overall {overall:.1%}.",
        recommendation=(
            "Treat this channel as low-LTV: cap acquisition spend, add a strong "
            "second-purchase nurture (email/offer), and weight CAC against realistic repeat value."
        ),
    )


_CHECKS = (
    _check_margin_dip,
    _check_west_conversion,
    _check_return_subcategory,
    _check_repeat_rate_channel,
)


def detect_anomalies() -> list[Anomaly]:
    """Run every check; return the anomalies found (skips any check that errors)."""
    found: list[Anomaly] = []
    for check in _CHECKS:
        try:
            a = check()
        except Exception:  # noqa: BLE001 — one bad check must not sink the run
            a = None
        if a is not None:
            found.append(a)
    return found


def detect_anomalies_text() -> str:
    """Human/agent-readable rendering of `detect_anomalies`."""
    anomalies = detect_anomalies()
    if not anomalies:
        return "No anomalies detected against the prior period."
    lines = [f"Detected {len(anomalies)} anomaly(ies):"]
    for i, a in enumerate(anomalies, 1):
        lines.append(
            f"\n{i}. [{a.severity.upper()}] {a.metric}\n"
            f"   Finding: {a.finding}\n"
            f"   Evidence: {a.evidence}\n"
            f"   Recommendation: {a.recommendation}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(detect_anomalies_text())
