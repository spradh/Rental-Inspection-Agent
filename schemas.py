"""Shared data contracts for the BI Analyst Agent.

Every layer (tools, agents, api, streamlit) imports these — so the shapes are defined
once. Keep this module dependency-free (only pydantic) to avoid import cycles.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A retrieved knowledge-base passage, with its source for citation."""

    text: str
    source: str
    score: float = 0.0


class ChartSeries(BaseModel):
    """One named numeric series in a chart (e.g. 'net_revenue')."""

    name: str
    values: list[float]


class ChartSpec(BaseModel):
    """A render-agnostic chart the agent built from REAL query rows (never invented).

    Deliberately minimal and serializable so it travels through the JSON API and is trivial
    to render (Streamlit st.bar_chart / line_chart / area_chart, or any charting lib). `x` are
    the category/time labels; each series supplies one value per label.
    """

    type: Literal["bar", "line", "area"] = "bar"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    x: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)


class AnalystAnswer(BaseModel):
    """The structured result the agent returns — never free text alone.

    Downstream (API, Streamlit, evals) consume this shape.
    """

    answer: str = Field(description="The analyst's answer, in prose.")
    evidence: list[str] = Field(default_factory=list, description="Key facts/numbers the answer rests on.")
    recommendations: list[str] = Field(default_factory=list, description="Ranked, actionable next steps.")
    sql_used: list[str] = Field(default_factory=list, description="Any SQL the agent ran.")
    citations: list[str] = Field(default_factory=list, description="KB sources used (e.g. data/docs/metric-definitions.md).")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    chart: Optional[ChartSpec] = Field(default=None, description="An optional chart to render alongside the prose.")


class Anomaly(BaseModel):
    """A KPI deviation surfaced by the Watch capability."""

    metric: str
    finding: str
    severity: str = "medium"            # low | medium | high
    evidence: str = ""                  # the number(s) behind it
    recommendation: str = ""
