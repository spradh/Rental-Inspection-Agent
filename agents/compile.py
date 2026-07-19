"""The one reasoning step: reconcile narration + visual signal into an InspectionReport.

`compile_report` builds a single interleaved timeline from the two streams
`tools.perception.analyze_video` produced, asks the LLM to categorize it into the
standard room-by-room report, and mark each finding's provenance — narrated, visual-only,
or both. This is also the ONE place the narrated-vs-visual judgment is made; a finding
found only in the visual stream becomes a flag for the PM to confirm/dismiss via
InspectionReport.flagged_for_review(), never a second LLM pass.

This module makes no LLM/network calls on import.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from project.config import COMPILE_MODEL
from project.schemas import (
    InspectionReport,
    SessionType,
    TranscriptSegment,
    VisualObservation,
)
from shared.llm import chat

_SYSTEM = """You are compiling a move-in/move-out condition report for a property manager \
from two independent, timestamped signals gathered from one walkthrough video of a VACANT \
rental unit:
  1. NARRATION — what the PM said aloud while walking through.
  2. VISUAL — what was independently observed to be visible in the video.

Group these into a room-by-room report: one entry per room actually shown in the video \
(e.g. "kitchen", "primary bedroom", "hallway bathroom"), each holding its own list of \
findings. For each distinct item worth recording, within its room's findings:
- Assign ONE category: walls_paint, floors, cleanliness, appliances, fixtures_hardware,
  windows_screens, or general_condition.
- Write a concrete, descriptive `description` of what was observed (e.g. "scuff mark on the
  wall to the left of the door", "carpet appears clean and unstained", "blinds missing from
  the bedroom window"). NEVER reduce this to a good/bad/poor label or a numeric condition
  score — describe, don't judge. NEVER estimate a dollar cost.
- Set `source` to "narration" if the PM mentioned it, "visual" if only the visual signal
  caught it, or "both" if they corroborate each other.
- Set `narrated` to true iff `source` is "narration" or "both" — false iff `source` is
  "visual" only. This flag is what surfaces the item to the PM for confirm/dismiss, so get
  it right: only mark narrated=false when the PM truly never mentioned this item, even in
  different words.
- Set `timestamp` to the [start_s, end_s) window (seconds) where this was observed.
- Set `confidence` (0-1) honestly — lower for something ambiguous or only briefly glimpsed.

Write a brief overall `summary` (2-4 sentences, no dollar figures, no good/bad verdict).

Return a single JSON object matching this schema (no prose, no code fences):
{schema}
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _render_timeline(
    transcript: list[TranscriptSegment], visual: list[VisualObservation]
) -> str:
    events = [(s.start_s, "NARRATION", s.text) for s in transcript]
    events += [(v.start_s, "VISUAL", v.description) for v in visual]
    events.sort(key=lambda e: e[0])
    return "\n".join(
        f"[{start:6.1f}s] {kind}: {text}" for start, kind, text in events
    ) or "(no signal captured)"


def compile_report(
    transcript: list[TranscriptSegment],
    visual: list[VisualObservation],
    *,
    session_type: SessionType,
    video_duration_s: float,
) -> InspectionReport:
    """Merge narration + visual signal into a validated, categorized InspectionReport.

    Prompts once, validates against the schema, and repairs once on a ValidationError.
    If repair also fails, degrades to a low-confidence report with no findings rather
    than raising — never leaves the caller with an unhandled exception.
    """
    schema_dict = InspectionReport.model_json_schema()
    schema = json.dumps(schema_dict)
    timeline = _render_timeline(transcript, visual)
    base_prompt = (
        _SYSTEM.format(schema=schema)
        + f"\nSession type: {session_type}\nVideo duration: {video_duration_s:.1f}s\n\n"
        + f"Timeline:\n{timeline}"
    )

    raw = chat(base_prompt, model=COMPILE_MODEL)
    try:
        report = InspectionReport.model_validate_json(_strip_fences(raw))
    except ValidationError as e:
        repair = (
            f"{base_prompt}\n\nYour previous reply was invalid:\n{raw}\n\n"
            f"It failed validation with:\n{e}\nReturn ONLY corrected JSON."
        )
        raw = chat(repair, model=COMPILE_MODEL)
        try:
            report = InspectionReport.model_validate_json(_strip_fences(raw))
        except ValidationError:
            report = InspectionReport(
                session_type=session_type,
                video_duration_s=video_duration_s,
                findings=[],
                summary=(
                    "The report could not be compiled into a structured format this "
                    "time. Please retry."
                ),
            )

    report.session_type = session_type
    report.video_duration_s = video_duration_s
    if not report.generated_at:
        report.generated_at = datetime.now(timezone.utc).isoformat()
    return report
