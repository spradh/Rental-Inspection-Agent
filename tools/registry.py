"""Tool registry — the single place every capability is wired up.

The agent loop never imports tools directly; it asks the registry for specs, renders
them as Anthropic-shaped tool schemas for native tool-calling, and `dispatch`es calls
back here. Each `ToolSpec` pairs a callable with a description and (optionally) a
pydantic args model used to validate inputs before the call.

Public surface (re-exported from project.tools):
    REGISTRY        — dict[name, ToolSpec] of every tool
    get_tools(names)— pick a subset of specs
    dispatch(name, args) -> str   — validate + call + capture errors (always a string)
    tool_schemas(names=None)      — [{name, description, input_schema}] for the API

Robustness: dispatch never raises — bad names, bad args, and tool exceptions all come
back as readable strings the agent can react to.

Demo:
    python -m project.tools.registry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

# ── tool callables ───────────────────────────────────────────────────────────
from project.tools.actions import churn_risk, inventory_reorder, recommend, what_if
from project.tools.anomalies import detect_anomalies_text
from project.tools.charts import plot
from project.tools.forecast import forecast_demand, forecast_net_revenue
from project.tools.kb import lookup_metric, search_kb
from project.tools.sql import get_schema, run_sql
from project.tools.web_analytics import web_analytics


# ── args models (pydantic) — validate + auto-document inputs ──────────────────
class RunSqlArgs(BaseModel):
    sql: str = Field(description="A single read-only SELECT statement over the warehouse.")


class PlotArgs(BaseModel):
    sql: str = Field(
        description=(
            "A read-only SELECT for the chart DATA: the first column is the x-axis (labels), "
            "and each remaining NUMERIC column becomes a series. e.g. "
            "SELECT substr(order_ts,1,7) AS month, SUM(subtotal - discount) AS net_revenue "
            "FROM orders WHERE status='completed' GROUP BY month ORDER BY month"
        )
    )
    chart_type: Literal["bar", "line", "area"] = Field(
        default="bar", description="bar for category comparisons, line/area for trends over time."
    )
    title: str = Field(default="", description="A short chart title.")


class GetSchemaArgs(BaseModel):
    pass


class SearchKbArgs(BaseModel):
    query: str = Field(description="What to look up in the knowledge base.")
    top_n: int = Field(default=5, ge=1, le=20, description="How many passages to return.")


class LookupMetricArgs(BaseModel):
    name: str = Field(description="Metric name, e.g. 'Net revenue', 'Gross margin %', 'AOV'.")


class WebAnalyticsArgs(BaseModel):
    metric: str = Field(description="One of: conversion, add_to_cart, sessions.")
    region: Optional[str] = Field(default=None, description="West | Northeast | South | Midwest.")
    period: Optional[str] = Field(default=None, description="YYYY or YYYY-MM prefix of session_ts.")


class ForecastNetRevenueArgs(BaseModel):
    months_ahead: int = Field(default=3, ge=1, le=12, description="Months to forecast.")


class ForecastDemandArgs(BaseModel):
    subcategory: str = Field(description="Product subcategory, e.g. 'Rivet Slim Jeans'.")
    months_ahead: int = Field(default=3, ge=1, le=12, description="Months to forecast.")


class WhatIfArgs(BaseModel):
    scenario: str = Field(description="The scenario and its assumptions to reason about.")


class RecommendArgs(BaseModel):
    context: str = Field(description="Findings/numbers to turn into ranked recommendations.")


class NoArgs(BaseModel):
    pass


# ── ToolSpec + helpers ───────────────────────────────────────────────────────
@dataclass
class ToolSpec:
    """One tool: a name, a description, a callable, and an optional args model."""

    name: str
    description: str
    func: Callable[..., Any]
    args_model: type[BaseModel] = field(default=NoArgs)

    def input_schema(self) -> dict:
        """Anthropic-shaped JSON schema for the tool's inputs."""
        schema = self.args_model.model_json_schema()
        # Anthropic expects an object schema with properties; ensure the shape.
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.pop("title", None)
        return schema


def _forecast_net_revenue_str(months_ahead: int = 3) -> str:
    """String wrapper around the forecast tool so observations are agent-readable."""
    pts = forecast_net_revenue(months_ahead)
    tail = pts[-(months_ahead + 3):]
    return "Net revenue (actual + forecast):\n" + "\n".join(
        f"  {p.month}  {p.value:>14,.2f}  {p.kind}" for p in tail
    )


def _forecast_demand_str(subcategory: str, months_ahead: int = 3) -> str:
    pts = forecast_demand(subcategory, months_ahead)
    tail = pts[-(months_ahead + 3):]
    return f"Demand for '{subcategory}' (units; actual + forecast):\n" + "\n".join(
        f"  {p.month}  {p.value:>12,.0f}  {p.kind}" for p in tail
    )


# ── the registry ─────────────────────────────────────────────────────────────
REGISTRY: dict[str, ToolSpec] = {
    "run_sql": ToolSpec(
        name="run_sql",
        description=(
            "Execute a single read-only SELECT over the Loom & Co. SQLite warehouse and "
            "return the result as a compact text table. Use get_schema first if unsure of "
            "columns. Only status='completed' orders count toward revenue."
        ),
        func=run_sql,
        args_model=RunSqlArgs,
    ),
    "plot": ToolSpec(
        name="plot",
        description=(
            "Render a chart for the user from warehouse data. Call this when the question asks "
            "to plot/visualize/show a chart or a trend/comparison (e.g. 'over time', 'by "
            "region', 'by month'). Pass a SELECT whose first column is the x-axis and whose "
            "remaining numeric columns are the series; the chart is drawn from the real rows "
            "and shown alongside your written answer."
        ),
        func=plot,
        args_model=PlotArgs,
    ),
    "get_schema": ToolSpec(
        name="get_schema",
        description="Return the warehouse schema (CREATE TABLE statements) so you know the tables/columns.",
        func=get_schema,
        args_model=GetSchemaArgs,
    ),
    "search_kb": ToolSpec(
        name="search_kb",
        description=(
            "Semantic search over the knowledge base (data dictionary, metric definitions, "
            "glossary, policies). Returns passages with [source] citations. Use this to "
            "ground terms before writing SQL."
        ),
        func=search_kb,
        args_model=SearchKbArgs,
    ),
    "lookup_metric": ToolSpec(
        name="lookup_metric",
        description=(
            "Return the canonical definition of a named KPI (e.g. 'Net revenue', "
            "'Gross margin %', 'AOV') from metric-definitions.md. Use the house definition, "
            "not your own."
        ),
        func=lookup_metric,
        args_model=LookupMetricArgs,
    ),
    "web_analytics": ToolSpec(
        name="web_analytics",
        description=(
            "Compute a web-funnel metric over web_sessions: conversion, add_to_cart, or "
            "sessions. Optionally slice by region (West/Northeast/South/Midwest) and period "
            "(YYYY or YYYY-MM)."
        ),
        func=web_analytics,
        args_model=WebAnalyticsArgs,
    ),
    "forecast_net_revenue": ToolSpec(
        name="forecast_net_revenue",
        description=(
            "Forecast monthly net revenue (Holt-Winters) and return recent actuals "
            "plus the next N forecast months."
        ),
        func=_forecast_net_revenue_str,
        args_model=ForecastNetRevenueArgs,
    ),
    "forecast_demand": ToolSpec(
        name="forecast_demand",
        description=(
            "Forecast monthly unit demand for a product subcategory (Holt-Winters), "
            "returning recent actuals plus the next N forecast months."
        ),
        func=_forecast_demand_str,
        args_model=ForecastDemandArgs,
    ),
    "what_if": ToolSpec(
        name="what_if",
        description=(
            "Reason over the net-revenue forecast and a stated scenario/assumptions to "
            "estimate directional impact on revenue and margin."
        ),
        func=what_if,
        args_model=WhatIfArgs,
    ),
    "recommend": ToolSpec(
        name="recommend",
        description="Turn findings/context into 3-5 ranked, specific, actionable recommendations.",
        func=recommend,
        args_model=RecommendArgs,
    ),
    "inventory_reorder": ToolSpec(
        name="inventory_reorder",
        description=(
            "Compare forecast demand to current stock (on_hand/reserved vs reorder_point) "
            "and list subcategories that need reordering."
        ),
        func=inventory_reorder,
        args_model=NoArgs,
    ),
    "churn_risk": ToolSpec(
        name="churn_risk",
        description=(
            "Surface at-risk customer segments and revenue exposure (one-and-done rate by "
            "acquisition channel, e.g. the low-loyalty flashdeal cohort)."
        ),
        func=churn_risk,
        args_model=NoArgs,
    ),
    "detect_anomalies": ToolSpec(
        name="detect_anomalies",
        description=(
            "Run the Watch checks (margin dip, West conversion drop, high-return "
            "subcategory, low repeat-rate channel) vs the prior period and report any "
            "anomalies found."
        ),
        func=detect_anomalies_text,
        args_model=NoArgs,
    ),
}


def get_tools(names: list[str]) -> list[ToolSpec]:
    """Return the ToolSpecs for the given names (silently skips unknown names)."""
    return [REGISTRY[n] for n in names if n in REGISTRY]


def tool_schemas(names: Optional[list[str]] = None) -> list[dict]:
    """Anthropic-shaped tool definitions: [{name, description, input_schema}]."""
    specs = get_tools(names) if names is not None else list(REGISTRY.values())
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.input_schema(),
        }
        for s in specs
    ]


def dispatch(name: str, args: dict | None = None) -> str:
    """Validate args against the tool's model, call it, and return a string result.

    Never raises: unknown tool, validation failure, and tool exceptions all return a
    readable error string.
    """
    spec = REGISTRY.get(name)
    if spec is None:
        return f"dispatch error: unknown tool {name!r}. Available: {', '.join(REGISTRY)}"
    args = args or {}
    if not isinstance(args, dict):
        return f"dispatch error: args for {name!r} must be an object, got {type(args).__name__}."
    try:
        validated = spec.args_model(**args)
    except Exception as e:  # noqa: BLE001 — pydantic ValidationError et al.
        return f"dispatch error: invalid args for {name!r}: {e}"
    try:
        result = spec.func(**validated.model_dump())
    except Exception as e:  # noqa: BLE001 — keep the agent loop alive
        return f"{name} error: {e}"
    return result if isinstance(result, str) else str(result)


if __name__ == "__main__":
    print("Registered tools:", ", ".join(REGISTRY))
    print(f"\n{len(tool_schemas())} schemas generated.")
    print("\nrun_sql input_schema:", REGISTRY["run_sql"].input_schema())
    print("\nDispatch demo (get_schema):")
    print(dispatch("get_schema", {})[:200], "...")
