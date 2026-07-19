"""Agents package — the Pre-Inspect "brain" pipeline.

Public surface:
    run_inspection    — main entrypoint: video in -> InspectionReport out
    InspectionReport  — the structured result shape (re-exported from project.schemas)
"""

from __future__ import annotations

from project.schemas import InspectionReport

from project.agents.pipeline import run_inspection

__all__ = [
    "run_inspection",
    "InspectionReport",
]
