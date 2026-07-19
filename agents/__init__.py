"""Agents package — the multi-agent graph at the heart of the BI Analyst Agent.

Public surface:
    ask                 — main entrypoint: guard + memory + graph -> AnalystAnswer
    build_graph         — compiled LangGraph runnable (with a checkpointer)
    generate_report     — autonomous weekly-review narrative (Monday Workbench)
    weekly_review_data  — raw anomalies + forecast points for the UI
    AnalystAnswer       — the structured result shape (re-exported from project.schemas)
"""

from __future__ import annotations

from project.schemas import AnalystAnswer

from project.agents.followups import suggest_followups
from project.agents.graph import ask, build_graph
from project.agents.report import generate_report, weekly_review_data

__all__ = [
    "ask",
    "build_graph",
    "generate_report",
    "weekly_review_data",
    "suggest_followups",
    "AnalystAnswer",
]
