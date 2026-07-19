"""Action & reasoning tools — where the agent goes from analysis to advice.

These tools combine deterministic data (forecasts, SQL aggregates) with light LLM
reasoning to produce decisions and recommendations:

  - what_if(scenario)   — reason over the net-revenue forecast + the scenario's stated
                          assumptions (LLM, cheap haiku model).
  - recommend(context)  — turn a situation into ranked, actionable next steps (LLM).
  - inventory_reorder() — compare forecast demand to current stock; list SKUs/subcats
                          to reorder (deterministic SQL + forecast).
  - churn_risk()        — at-risk segments and revenue exposure (deterministic SQL),
                          e.g. the low-loyalty flashdeal cohort.

Each returns a STRING observation and never raises. LLM calls use the cheap tool-
reasoning model; if the LLM is unreachable, the tool degrades to the raw data + a note.

Demo:
    python -m project.tools.actions
"""

from __future__ import annotations

from project.tools.forecast import forecast_demand, forecast_net_revenue
from project.tools.sql import query_rows

# Cheap model for tool-level reasoning (per project conventions).
_TOOL_MODEL = "anthropic:claude-haiku-4-5"


def _llm(system: str, user: str) -> str | None:
    """Call the shared LLM; return None on any failure so callers can degrade."""
    try:
        from shared.llm import chat

        return chat(
            [{"role": "user", "content": user}],
            system=system,
            model=_TOOL_MODEL,
            temperature=0.2,
            max_tokens=600,
        ).strip()
    except Exception:  # noqa: BLE001 — keep tools robust if the LLM is unavailable
        return None


def _net_revenue_context(months_ahead: int = 3) -> str:
    """Render recent actuals + forecast for net revenue as a compact text block."""
    try:
        pts = forecast_net_revenue(months_ahead)
    except Exception as e:  # noqa: BLE001
        return f"(forecast unavailable: {e})"
    tail = pts[-(months_ahead + 3):]
    return "\n".join(f"  {p.month}  {p.value:>14,.0f}  {p.kind}" for p in tail)


def what_if(scenario: str) -> str:
    """Reason over the net-revenue forecast + the scenario's assumptions."""
    if not isinstance(scenario, str) or not scenario.strip():
        return "what_if: provide a scenario to reason about."
    forecast_block = _net_revenue_context()
    user = (
        f"Net-revenue forecast (actual + forecast months):\n{forecast_block}\n\n"
        f"Scenario / assumptions: {scenario}\n\n"
        "Estimate the directional impact on net revenue and margin over the forecast "
        "horizon. State the key assumptions you made and your reasoning. Be concise "
        "(<150 words) and quantify where the numbers above let you."
    )
    system = (
        "You are a BI analyst doing what-if reasoning for Loom & Co. (DTC apparel). "
        "Ground every claim in the forecast numbers provided; flag where you are "
        "extrapolating. Do not invent data."
    )
    out = _llm(system, user)
    if out is None:
        return (
            "what_if (LLM unavailable — raw context only):\n"
            f"Net-revenue forecast:\n{forecast_block}\n\nScenario: {scenario}"
        )
    return f"What-if: {scenario}\n\n{out}\n\nBasis (net-revenue forecast):\n{forecast_block}"


def recommend(context: str) -> str:
    """Turn a situation into ranked, actionable next steps."""
    if not isinstance(context, str) or not context.strip():
        return "recommend: provide context (findings/numbers) to recommend on."
    system = (
        "You are a BI analyst for Loom & Co. (DTC apparel). Given findings, return 3-5 "
        "ranked, specific, actionable recommendations. Each: one line, lead with the "
        "action verb, note the expected impact. No preamble."
    )
    out = _llm(system, f"Findings/context:\n{context}")
    if out is None:
        return f"recommend (LLM unavailable): consider acting on — {context}"
    return f"Recommended actions:\n{out}"


def inventory_reorder() -> str:
    """Compare forecast demand to current stock; list items to reorder."""
    rows = query_rows(
        """
        SELECT p.subcategory                  AS subcat,
               SUM(i.units_on_hand)            AS on_hand,
               SUM(i.units_reserved)           AS reserved,
               SUM(i.reorder_point)            AS reorder_point
        FROM inventory i
        JOIN products p ON p.product_id = i.product_id
        GROUP BY p.subcategory
        ORDER BY subcat
        """
    )
    if isinstance(rows, str):
        return f"inventory_reorder: {rows}"
    if not rows:
        return "inventory_reorder: no inventory data available."

    lines: list[str] = []
    flagged = 0
    for subcat, on_hand, reserved, reorder_point in rows:
        on_hand = on_hand or 0
        reserved = reserved or 0
        reorder_point = reorder_point or 0
        available = on_hand - reserved
        # Next-month forecast demand for this subcategory (needs >=12 months history).
        try:
            fc = forecast_demand(subcat, months_ahead=1)
            next_demand = fc[-1].value
            demand_note = f"forecast next-mo demand ~{next_demand:,.0f}"
        except Exception:  # noqa: BLE001 — not enough history / unknown subcat
            next_demand = None
            demand_note = "forecast n/a"

        need_reorder = available <= reorder_point or (
            next_demand is not None and available < next_demand
        )
        if need_reorder:
            flagged += 1
            lines.append(
                f"  REORDER  {subcat}: available {available:,} "
                f"(on_hand {on_hand:,} − reserved {reserved:,}), "
                f"reorder_point {reorder_point:,}, {demand_note}"
            )

    if not lines:
        return "inventory_reorder: all subcategories above reorder point and forecast demand."
    header = f"inventory_reorder: {flagged} subcategory(ies) need attention:"
    return header + "\n" + "\n".join(lines)


def churn_risk() -> str:
    """At-risk segments and revenue exposure (e.g. the flashdeal cohort)."""
    rows = query_rows(
        """
        WITH cust AS (
          SELECT c.customer_id          AS cid,
                 c.acquisition_channel   AS chan,
                 COUNT(o.order_id)        AS n_orders,
                 SUM(o.subtotal - o.discount) AS net_rev,
                 MAX(o.order_ts)          AS last_order
          FROM customers c
          JOIN orders o ON o.customer_id = c.customer_id AND o.status = 'completed'
          GROUP BY c.customer_id
        )
        SELECT chan,
               COUNT(*)                                                AS buyers,
               SUM(CASE WHEN n_orders = 1 THEN 1 ELSE 0 END)           AS one_and_done,
               CAST(SUM(CASE WHEN n_orders = 1 THEN 1 ELSE 0 END) AS REAL)
                 / COUNT(*)                                            AS one_done_rate,
               ROUND(SUM(net_rev), 0)                                  AS net_rev,
               MAX(last_order)                                         AS latest_order
        FROM cust
        GROUP BY chan
        HAVING buyers >= 10
        ORDER BY one_done_rate DESC
        """
    )
    if isinstance(rows, str):
        return f"churn_risk: {rows}"
    if not rows:
        return "churn_risk: no customer order data available."

    total_buyers = sum(r[1] for r in rows)
    overall_one_done = (
        sum(r[2] for r in rows) / total_buyers if total_buyers else 0.0
    )
    lines = [
        "churn_risk — one-and-done (single-purchase) rate by acquisition channel "
        f"(overall {overall_one_done:.1%}):"
    ]
    for chan, buyers, one_done, rate, net_rev, latest in rows:
        flag = "  <-- AT RISK" if rate > overall_one_done * 1.2 else ""
        lines.append(
            f"  {chan:<12} buyers {buyers:>5,}  one-and-done {rate:>6.1%}  "
            f"lifetime net ${net_rev:>12,.0f}{flag}"
        )
    lines.append(
        "\nRevenue exposure = lifetime net of high one-and-done channels (e.g. flashdeal); "
        "these cohorts churn fastest, so retained second-purchase value is the lever."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(inventory_reorder())
    print()
    print(churn_risk())
