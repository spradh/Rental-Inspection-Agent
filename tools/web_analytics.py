"""Web analytics tool — conversion / add-to-cart / sessions over web_sessions.

A focused, parameterised wrapper around the `web_sessions` table so the agent can ask
for funnel KPIs without hand-writing SQL each time. Definitions follow
metric-definitions.md:
    conversion rate  = AVG(converted)
    add-to-cart rate = AVG(added_to_cart)
    sessions         = COUNT(*)

Optionally sliced by region (West/Northeast/South/Midwest) and period (YYYY or YYYY-MM
prefix on session_ts). Returns a STRING observation; never raises.

Demo:
    python -m project.tools.web_analytics
"""

from __future__ import annotations

from project.tools.sql import query_rows

# Map friendly metric names to (SQL expression, label, is_rate).
_METRICS = {
    "conversion": ("AVG(converted)", "conversion rate", True),
    "conversion_rate": ("AVG(converted)", "conversion rate", True),
    "add_to_cart": ("AVG(added_to_cart)", "add-to-cart rate", True),
    "add-to-cart": ("AVG(added_to_cart)", "add-to-cart rate", True),
    "cart": ("AVG(added_to_cart)", "add-to-cart rate", True),
    "sessions": ("COUNT(*)", "sessions", False),
}

_VALID_REGIONS = {"west", "northeast", "south", "midwest"}


def web_analytics(metric: str, region: str | None = None, period: str | None = None) -> str:
    """Compute a web-funnel metric over web_sessions, optionally by region/period.

    metric: one of conversion | add_to_cart | sessions
    region: West | Northeast | South | Midwest (optional)
    period: a YYYY or YYYY-MM prefix matched against session_ts (optional)
    """
    key = (metric or "").strip().lower().replace(" ", "_")
    spec = _METRICS.get(key)
    if spec is None:
        return (
            f"web_analytics: unknown metric {metric!r}. "
            f"Choose one of: conversion, add_to_cart, sessions."
        )
    expr, label, is_rate = spec

    where: list[str] = []
    params_note: list[str] = []
    if region:
        if region.strip().lower() not in _VALID_REGIONS:
            return (
                f"web_analytics: unknown region {region!r}. "
                f"Choose one of: West, Northeast, South, Midwest."
            )
        # region is validated against an allow-list, so inlining is safe.
        where.append(f"LOWER(region) = '{region.strip().lower()}'")
        params_note.append(f"region={region}")
    if period:
        p = period.strip()
        if not p.replace("-", "").isdigit() or len(p) not in (4, 7):
            return f"web_analytics: period must be YYYY or YYYY-MM, got {period!r}."
        where.append(f"substr(session_ts, 1, {len(p)}) = '{p}'")
        params_note.append(f"period={p}")

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT {expr} AS metric, COUNT(*) AS n_sessions "
        f"FROM web_sessions{clause}"
    )
    result = query_rows(sql)
    if isinstance(result, str):
        return result  # error string
    if not result or result[0][0] is None:
        return f"web_analytics: no sessions matched ({', '.join(params_note) or 'all'})."

    value, n_sessions = result[0]
    scope = ", ".join(params_note) if params_note else "all sessions"
    if is_rate:
        return (
            f"{label} = {float(value) * 100:.2f}% "
            f"({scope}; n={n_sessions} sessions)"
        )
    return f"{label} = {int(value):,} ({scope})"


if __name__ == "__main__":
    print(web_analytics("conversion"))
    print(web_analytics("conversion", region="West"))
    print(web_analytics("add_to_cart", period="2026-03"))
    print(web_analytics("sessions", region="West", period="2026"))
