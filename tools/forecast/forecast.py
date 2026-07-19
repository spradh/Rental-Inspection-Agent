"""The forecasting model for the BI Analyst Agent.

This is a **provided** model — students don't build it, they *wrap it as a tool* (the
Week 2 lesson: a tool can call a model, not just an API). The agent then reasons over
the predictions ("revenue is trending toward ~$X next month, driven by …").

Method: **Holt-Winters exponential smoothing** (statsmodels `ExponentialSmoothing`) —
an additive damped trend with additive seasonality. Damping keeps the trend from running
away on a strongly-growing series; the seasonal term captures the Q4 lift. Additive
seasonality (not multiplicative) is deliberate: it's robust on *both* the dense net-revenue
series and the small, noisy per-subcategory demand counts, where a multiplicative seasonal
overfits and collapses individual months. Falls back to a non-seasonal fit when there
aren't two full seasonal cycles yet.

statsmodels is imported lazily inside the fit, so this module stays cheap to import.

Run a demo:
    python -m project.tools.forecast
"""

from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DB = REPO_ROOT / "data" / "local" / "loomco.db"

SEASON = 12  # monthly data -> a 12-month seasonal cycle


@dataclass
class Point:
    month: str        # "YYYY-MM"
    value: float
    kind: str         # "actual" | "forecast"


# ── the model ────────────────────────────────────────────────────────────────
def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def _holt_winters_forecast(ys: list[float], months_ahead: int) -> list[float]:
    """Fit Holt-Winters and return `months_ahead` point forecasts (clamped >= 0).

    Adds an additive seasonal term once there are >= 2 full cycles of history; very short
    series fall back to a flat last-value carry-forward.
    """
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    if len(ys) < 4:  # too short to fit a trend — carry the last value forward
        return [max(ys[-1], 0.0)] * months_ahead

    kwargs: dict = {"trend": "add", "damped_trend": True, "initialization_method": "estimated"}
    if len(ys) >= 2 * SEASON:  # enough history for seasonality
        kwargs["seasonal"] = "add"
        kwargs["seasonal_periods"] = SEASON

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # quiet the optimizer's convergence chatter
        fit = ExponentialSmoothing(ys, **kwargs).fit()
        forecast = fit.forecast(months_ahead)
    return [max(float(v), 0.0) for v in forecast]


def forecast_series(history: list[tuple[str, float]], months_ahead: int = 3) -> list[Point]:
    """Forecast a monthly series. `history` = [(YYYY-MM, value), …] in order."""
    if len(history) < 12:
        raise ValueError("need at least 12 months of history for seasonality")
    months = [m for m, _ in history]
    ys = [float(v) for _, v in history]

    out = [Point(m, v, "actual") for m, v in history]
    preds = _holt_winters_forecast(ys, months_ahead)
    ym = months[-1]
    for value in preds:
        ym = _next_month(ym)
        out.append(Point(ym, round(value, 2), "forecast"))
    return out


# ── data access (the bits a tool wrapper calls) ──────────────────────────────
def _monthly_net_revenue(db: Path = DB) -> list[tuple[str, float]]:
    con = sqlite3.connect(db)
    rows = con.execute(
        """
        SELECT substr(order_ts, 1, 7) ym, ROUND(SUM(subtotal) - SUM(discount), 2) net
        FROM orders WHERE status = 'completed'
        GROUP BY ym ORDER BY ym
        """
    ).fetchall()
    con.close()
    return [(m, float(v)) for m, v in rows]


def _monthly_units(subcategory: str, db: Path = DB) -> list[tuple[str, float]]:
    con = sqlite3.connect(db)
    rows = con.execute(
        """
        SELECT substr(o.order_ts, 1, 7) ym, SUM(oi.quantity) units
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE o.status = 'completed' AND p.subcategory = ?
        GROUP BY ym ORDER BY ym
        """,
        (subcategory,),
    ).fetchall()
    con.close()
    return [(m, float(v)) for m, v in rows]


def forecast_net_revenue(months_ahead: int = 3, db: Path = DB) -> list[Point]:
    return forecast_series(_monthly_net_revenue(db), months_ahead)


def forecast_demand(subcategory: str, months_ahead: int = 3, db: Path = DB) -> list[Point]:
    history = _monthly_units(subcategory, db)
    if len(history) < 12:
        raise ValueError(f"not enough history for subcategory {subcategory!r}")
    return forecast_series(history, months_ahead)


if __name__ == "__main__":
    if not DB.exists():
        raise SystemExit("loomco.db not found — run: python -m data.generate")
    print("Net revenue forecast (last 3 actuals + 3 forecast):")
    for p in forecast_net_revenue(3)[-6:]:
        print(f"  {p.month}  {p.value:>12,.0f}  {p.kind}")
