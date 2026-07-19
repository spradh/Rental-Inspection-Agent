"""Fused narration transcription + visual analysis via a video-native multimodal LLM.

Sends the whole video (with its audio track) to Gemini 2.5 Flash, via OpenRouter, in one
request, and asks for two purely descriptive, timestamped streams back: what the PM said,
and what's visibly present. No categorization, no room-tagging, and no condition judgment
here — that reconciliation happens once, in agents.compile, where both signals can be seen
side by side.

NOTE: the exact multimodal request shape for a video+audio content part is a documented
assumption, not yet verified against a live OpenRouter call — smoke-test this against one
real short narrated clip before relying on it (see the project plan).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
from pydantic import BaseModel, ValidationError

from project.config import PERCEPTION_MODEL
from project.schemas import TranscriptSegment, VisualObservation

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM = """You are transcribing and visually describing a real-estate walkthrough video for \
a documentation tool. The video shows a property manager walking through a VACANT rental unit, \
narrating aloud what they see.

Return ONLY a single JSON object with this exact shape (no prose, no code fences):
{
  "transcript": [{"start_s": <float>, "end_s": <float>, "text": "<verbatim narration>"}, ...],
  "visual": [{"start_s": <float>, "end_s": <float>, "description": "<what's visible>"}, ...]
}

Rules:
- "transcript": segment the PM's spoken narration verbatim, in order, with accurate timestamps.
  If a span has no speech, do not emit a segment for it.
- "visual": independently describe what's visibly present across the WHOLE video at regular
  intervals, regardless of whether the PM is talking — include ambient context (which room,
  fixtures, surfaces) as well as anything notable (marks, stains, damage, missing items, general
  cleanliness). Describe only what you can actually see; never invent detail.
- NEVER render a condition judgment (no "good"/"bad"/"poor" labels, no ratings, no scores) in
  either list — describe observations in concrete, descriptive terms only.
- NEVER estimate a dollar cost or value.
- Timestamps are seconds from the start of the video (floats)."""


class _PerceptionPayload(BaseModel):
    transcript: list[TranscriptSegment] = []
    visual: list[VisualObservation] = []


def _video_data_uri(video_path: Path) -> str:
    data = video_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    suffix = video_path.suffix.lstrip(".").lower() or "mp4"
    return f"data:video/{suffix};base64,{b64}"


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def analyze_video(
    video_path: str | Path,
) -> tuple[list[TranscriptSegment], list[VisualObservation]]:
    """Run the fused perception call and return (transcript, visual observations).

    Raises RuntimeError on a missing API key, a failed request, or a response that
    doesn't match the expected schema. Callers (agents.pipeline) decide how to degrade.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    provider, _, model = PERCEPTION_MODEL.partition(":")
    if provider != "openrouter":
        raise RuntimeError(
            f"tools.perception only supports an 'openrouter:...' PERCEPTION_MODEL, "
            f"got {PERCEPTION_MODEL!r}"
        )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe and describe this walkthrough video."},
                    {
                        "type": "video_url",
                        "video_url": {"url": _video_data_uri(Path(video_path))},
                    },
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"perception request failed: {e} — {resp.text[:500]}") from e

    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        payload = _PerceptionPayload.model_validate_json(_strip_fences(raw))
    except (ValidationError, json.JSONDecodeError) as e:
        raise RuntimeError(f"perception response did not match the expected schema: {e}") from e

    return payload.transcript, payload.visual


if __name__ == "__main__":
    import sys

    transcript, visual = analyze_video(sys.argv[1])
    print(f"{len(transcript)} transcript segments, {len(visual)} visual observations")
