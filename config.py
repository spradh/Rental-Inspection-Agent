"""Central configuration for the Pre-Inspect pipeline.

One place for model choices and pipeline limits so the rest of the package never reads
os.environ directly. Values come from the repo .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = two levels up from this file (project/config.py -> project -> repo root).
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# ── Models (provider:model — resolved by shared.llm) ─────────────
# Perception: one fused call (narration transcript + visual observations) over the raw
# video+audio. Gemini natively ingests a video's audio and visual frames together.
PERCEPTION_MODEL = os.getenv("PERCEPTION_MODEL", "openrouter:google/gemini-2.5-flash")
# Compile: text-only reasoning step that merges perception output into an InspectionReport.
# No reason to leave the existing Claude tier for a structured-output-only call.
COMPILE_MODEL = os.getenv("COMPILE_MODEL", "anthropic:claude-sonnet-4-6")

# ── Pipeline limits ────────────────────────────────────────────────
# The PRD's upload cap (target 2-3 min, hard limit under 5 min).
MAX_VIDEO_S = int(os.getenv("MAX_VIDEO_S", "300"))


def status() -> str:
    """One-line summary of the active configuration (no secrets)."""
    return f"perception={PERCEPTION_MODEL} | compile={COMPILE_MODEL} | max_video_s={MAX_VIDEO_S}"


if __name__ == "__main__":
    print(status())
