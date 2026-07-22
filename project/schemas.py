"""Shared data contracts for the Pre-Inspect pipeline.

Every layer (tools, agents) imports these — so the shapes are defined once. Keep this
module dependency-free (only pydantic) to avoid import cycles.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "walls_paint",
    "floors",
    "cleanliness",
    "appliances",
    "fixtures_hardware",
    "windows_screens",
    "general_condition",
]
SessionType = Literal["move_in", "move_out"]
Source = Literal["narration", "visual", "both"]


class TimestampRef(BaseModel):
    """A [start, end) window into the source video, in seconds."""

    start_s: float
    end_s: float


class TranscriptSegment(BaseModel):
    """One timestamped slice of the PM's narration (tools.perception output)."""

    start_s: float
    end_s: float
    text: str


class VisualObservation(BaseModel):
    """Something visibly present in the video, independent of narration.

    Purely descriptive (tools.perception output) — no category, no room, no condition
    judgment yet. agents.compile reconciles this against the transcript.
    """

    start_s: float
    end_s: float
    description: str


class Finding(BaseModel):
    """One atomic item within a RoomReport.

    `description` documents what was observed (e.g. "scuff mark on the wall near the
    doorway") — it must never be reduced to a good/bad rating or a condition score; see
    InspectionReport's docstring for why.
    """

    category: Category
    description: str
    timestamp: TimestampRef
    source: Source
    narrated: bool = Field(description="False iff source == 'visual' (unnarrated but visible).")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class RoomReport(BaseModel):
    """All findings for one room, grouped the way a PM reads the report."""

    room: str
    findings: list[Finding] = Field(default_factory=list)


class FlaggedFinding(Finding):
    """A Finding surfaced for PM confirm/dismiss, with its room re-attached.

    Returned by InspectionReport.flagged_for_review() — a flat, self-contained shape for
    a review queue, independent of the report's room-grouped body.
    """

    room: str


class InspectionReport(BaseModel):
    """The Week-1 deliverable: a compiled, room-by-room condition report.

    Per the PRD's non-negotiables, this documents condition — it is never a Good/Bad
    verdict and never a dollar figure. Each Finding's `description` carries the actual
    observed detail; `flagged_for_review` derives (not re-judges) which findings the PM
    never narrated, for them to confirm or dismiss.
    """

    session_type: SessionType
    video_duration_s: float
    rooms: list[RoomReport] = Field(default_factory=list)
    summary: str = ""
    generated_at: str = ""

    def flagged_for_review(self) -> list[FlaggedFinding]:
        """Findings visible in the video but never called out by the PM's narration."""
        return [
            FlaggedFinding(room=r.room, **f.model_dump())
            for r in self.rooms
            for f in r.findings
            if not f.narrated
        ]
