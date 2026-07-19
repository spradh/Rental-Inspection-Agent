"""The Pre-Inspect "brain": narrated walkthrough video in, InspectionReport out.

Public API:
    run_inspection(video_path, *, session_type) -> InspectionReport

Three steps, always in this order — no branching, no routing decision, so this is a
plain function pipeline rather than a graph:
    tools.video.probe          — cheap local guardrail (duration, has audio) before
                                  spending an API call
    tools.perception.analyze_video — one fused call: narration transcript + visual
                                      observations
    agents.compile.compile_report  — one reasoning call: merge into a categorized,
                                      room-by-room InspectionReport

This module makes no LLM/network calls on import. A demo lives under __main__.

Run:
    python -m project.agents.pipeline <video_path> [move_in|move_out]
"""

from __future__ import annotations

from project.schemas import InspectionReport, SessionType
from project.tools.perception import analyze_video
from project.tools.video import probe

from project.agents.compile import compile_report


def run_inspection(video_path: str, *, session_type: SessionType) -> InspectionReport:
    """Run the full brain pipeline on one uploaded walkthrough video.

    Raises tools.video.VideoValidationError if the file fails the basic guardrails
    (missing, silent, too long). A perception failure (e.g. an empty transcript because
    the PM barely narrated) is NOT fatal — compile_report just leans harder on whatever
    visual signal came back; per the PRD, sparse narration is an expected case, not an
    error state.
    """
    meta = probe(video_path)

    try:
        transcript, visual = analyze_video(video_path)
    except RuntimeError:
        transcript, visual = [], []

    return compile_report(
        transcript,
        visual,
        session_type=session_type,
        video_duration_s=meta.duration_s,
    )


if __name__ == "__main__":
    import sys

    path = sys.argv[1]
    session = sys.argv[2] if len(sys.argv) > 2 else "move_in"
    report = run_inspection(path, session_type=session)
    print(report.model_dump_json(indent=2))
