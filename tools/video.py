"""Deterministic video-file utilities for the Pre-Inspect pipeline.

No LLM calls here — just a cheap, local guardrail on the uploaded file before it's sent
to the (paid, slower) perception step. Requires `ffprobe` (part of ffmpeg) on PATH.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel

from project.config import MAX_VIDEO_S


class VideoMeta(BaseModel):
    """Basic facts about an uploaded walkthrough video."""

    path: str
    duration_s: float
    has_audio: bool


class VideoValidationError(ValueError):
    """Raised when an uploaded file isn't a usable walkthrough video."""


def probe(path: str | Path) -> VideoMeta:
    """Inspect a video file with ffprobe and validate it against the PRD's constraints.

    Raises VideoValidationError if the file is missing, unreadable, silent (no audio
    track — the PM's narration is required), or longer than MAX_VIDEO_S.
    """
    p = Path(path)
    if not p.is_file():
        raise VideoValidationError(f"video not found: {p}")

    try:
        raw = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(p),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError as e:
        raise VideoValidationError("ffprobe is not installed / not on PATH") from e
    except subprocess.CalledProcessError as e:
        raise VideoValidationError(f"ffprobe could not read {p}: {e.stderr.strip()}") from e

    info = json.loads(raw)
    duration_s = float(info.get("format", {}).get("duration", 0.0))
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))

    if duration_s <= 0:
        raise VideoValidationError(f"{p} has no readable duration")
    if duration_s > MAX_VIDEO_S:
        raise VideoValidationError(
            f"video is {duration_s:.0f}s, over the {MAX_VIDEO_S}s limit"
        )
    if not has_audio:
        raise VideoValidationError(
            f"{p} has no audio track — narration is required for a walkthrough"
        )

    return VideoMeta(path=str(p), duration_s=duration_s, has_audio=has_audio)


if __name__ == "__main__":
    import sys

    print(probe(sys.argv[1]).model_dump_json(indent=2))
