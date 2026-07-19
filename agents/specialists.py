"""BI specialist agents — each owns a small slice of the project tool registry.

A specialist is a focused **native tool-calling** loop: a short system prompt + the handful
of tools it's good at (looked up from `project.tools` by name). The supervisor (in graph.py)
routes to one of these by `name`. Keeping each tool set small is the whole point — short
prompts, clean tool selection, isolated failure.

The four specialists mirror the Loom & Co. org (see project/README.md):
    sales        — Sales & Revenue        (run_sql, lookup_metric, forecast_net_revenue)
    marketing    — Marketing & Web        (run_sql, web_analytics, lookup_metric)
    product      — Product & Inventory     (run_sql, lookup_metric, inventory_reorder)
    forecasting  — Forecasting & Planning  (forecast_net_revenue, forecast_demand, what_if)

Each runs a native tool-calling loop (`shared.llm.run_tool_loop`) over its own tools, so
factual answers come from a real tool call rather than the model's memory. Using native tool
calling (not a hand-rolled JSON-ReAct protocol) keeps the agent **model-agnostic** — it
grounds correctly on Anthropic *and* OpenAI-compatible providers (OpenRouter, OpenAI).

This module makes no LLM/network calls on import.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from project.config import SPECIALIST_MODEL
from project.tools import dispatch, tool_schemas
from project.tools.sql import get_schema
from shared.llm import run_tool_loop

_SCHEMA_CACHE: str | None = None


def _warehouse_schema() -> str:
    """The warehouse schema + dialect note, fetched once and cached.

    Injected into the system prompt of any specialist that can `run_sql`, so it writes
    correct columns and the right dialect instead of guessing. `get_schema` isn't in a
    specialist's tool set, so this is how the model sees the real schema. Lazy (first
    `run()`), so import stays network-free."""
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = get_schema()
    return _SCHEMA_CACHE


_SYSTEM = """{system}

You are a specialist analyst for Loom & Co. (a DTC apparel brand). Use the available tools to
gather facts — call a tool for anything factual; never invent numbers. Look up a metric's
definition (lookup_metric) before you compute it. Values that come back as '[redacted]' are
masked by the data-access policy for the caller's role (NOT missing) — report the visible data
and note any redacted field is restricted by policy; do not claim there is no data. When you
have enough, reply with your findings in up to 5 sentences, citing the figures (and any
sources) you used."""


@dataclass
class Specialist:
    """One specialist agent: a routing name, a description, and its bound tools.

    `tools` is a list of tool *names* (keys into `project.tools`). The loop runs native tool
    calling over their schemas and executes each call through `dispatch()`, so every
    observation is a real string from a real tool.
    """

    name: str  # what the supervisor routes with, e.g. "sales"
    description: str  # one line the supervisor reads when choosing a route
    tools: list[str] = field(default_factory=list)
    system: str = ""  # the specialist's own system prompt
    max_steps: int = 5

    def run(self, query: str, context: str = "") -> tuple[str, Optional[dict]]:
        """Run the specialist's native tool-calling loop.

        `context` is recent conversation history (may be "") so the specialist can resolve a
        follow-up like "now chart that". Returns (findings, chart) where `chart` is a ChartSpec
        dict if the specialist drew one via the `plot` tool, else None.
        """
        system = _SYSTEM.format(system=self.system)
        # SQL-writing specialists get the real schema + dialect note up front, so they never
        # guess columns or dialect (the classic "EXTRACT on order_date" failure).
        if "run_sql" in self.tools:
            system += "\n\nWarehouse schema (write SQL for THESE tables/columns; dialect noted):\n" + _warehouse_schema()
        if "plot" in self.tools:
            system += (
                "\n\nIf the question asks to plot/visualize/show a chart or a trend/comparison "
                "(e.g. 'over time', 'by region', 'by month'), call `plot` with a SELECT that "
                "returns the chart data (first column = x-axis labels, remaining numeric columns "
                "= series), then describe what it shows."
            )

        user = f"{context}\n\nCurrent question: {query}" if context else query
        text, calls = run_tool_loop(
            model=SPECIALIST_MODEL,
            system=system,
            user=user,
            tools=tool_schemas(self.tools),
            execute=dispatch,
            max_steps=self.max_steps,
        )

        # Surface the ACTUAL SQL that ran (run_sql AND the chart's plot query) so
        # graph._extract_sql gets faithful provenance — and a fabricated/literal chart query
        # is visible in sql_used rather than hidden behind the rendered chart.
        ran_sql = [
            c["args"]["sql"].strip()
            for c in calls
            if c["name"] in ("run_sql", "plot") and c["args"].get("sql")
        ]
        if ran_sql:
            text = (text + "\n\nSQL run:\n" + "\n".join(ran_sql)).strip()

        # Capture the chart the model drew (last `plot` call). The tool returns the ChartSpec
        # as JSON on success, or a 'PlotError: …' string on failure (which won't parse → None).
        chart: Optional[dict] = None
        for c in calls:
            if c["name"] == "plot":
                try:
                    chart = json.loads(c["result"])
                except (json.JSONDecodeError, TypeError):
                    chart = None
        return (text or "(no findings)"), chart


# ── the specialist roster the supervisor routes over ───────────────────────────
SPECIALISTS: dict[str, Specialist] = {
    "sales": Specialist(
        name="sales",
        description=(
            "Sales, Revenue & Customers: net revenue, gross margin, AOV, discounts, returns "
            "impact by category/region/month; customer-level analysis (top customers, order "
            "counts, spend, lifetime value); near-term revenue projection."
        ),
        tools=["run_sql", "plot", "lookup_metric", "forecast_net_revenue"],
        system="You are a Sales & Revenue analyst. Quantify revenue and margin with SQL; "
        "look up the canonical metric definition before computing it.",
    ),
    "marketing": Specialist(
        name="marketing",
        description=(
            "Marketing & Web Analytics: conversion rate, add-to-cart, traffic by "
            "source/region, campaign spend & CAC."
        ),
        tools=["run_sql", "plot", "web_analytics", "lookup_metric"],
        system="You are a Marketing & Web Analytics analyst. Use web_analytics for "
        "conversion/traffic and run_sql for campaign spend; segment by region, source, and month.",
    ),
    "product": Specialist(
        name="product",
        description=(
            "Product & Inventory: SKU performance, return reasons & rates by product, "
            "stock vs. reorder point and what needs reordering."
        ),
        tools=["run_sql", "plot", "lookup_metric", "inventory_reorder"],
        system="You are a Product & Inventory analyst. Diagnose SKU-level issues — return "
        "reasons (fit/quality), return rates, and inventory positions — with SQL.",
    ),
    "forecasting": Specialist(
        name="forecasting",
        description=(
            "Forecasting & Planning: project net revenue and per-subcategory demand months "
            "ahead, and reason over what-if scenarios."
        ),
        tools=["forecast_net_revenue", "forecast_demand", "what_if"],
        system="You are a Forecasting & Planning analyst. Use the forecast tools for "
        "projections (they wrap a real model) and what_if to estimate scenario impact.",
    ),
}


def specialist_menu() -> str:
    """Render the route options for the supervisor's routing prompt."""
    return "\n".join(f"- {s.name}: {s.description}" for s in SPECIALISTS.values())


if __name__ == "__main__":
    print("Specialists:")
    print(specialist_menu())
