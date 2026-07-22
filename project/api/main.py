"""FastAPI service for Pre-Inspect — async, JSON, health check.

Production entrypoint for the video-walkthrough-to-report pipeline. The pipeline already
exists in `project.agents` (`run_inspection`); this layer just exposes it over HTTP.

Endpoints:
    GET  /health    -> readiness probe: ffprobe on PATH + an LLM provider key set for both
                       the perception and compile models.
    POST /inspect   -> upload a walkthrough video (multipart) + session_type, run the full
                       brain pipeline, and return the InspectionReport as JSON. The uploaded
                       video is always deleted after processing (never persisted) — see the
                       PRD's non-negotiable that raw video is discarded post-report.

Run locally (from repo root):
    uvicorn project.api.main:app --reload
    curl -s -X POST localhost:8000/inspect \
        -F "session_type=move_in" \
        -F "video=@walkthrough.mp4"
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from project.agents import InspectionReport, run_inspection
from project.config import COMPILE_MODEL, MAX_VIDEO_S, PERCEPTION_MODEL
from project.tools.video import VideoValidationError

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("pre-inspect")

app = FastAPI(title="Pre-Inspect Agent", version="1.0.0")

_PROVIDER_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _provider_ok(model: str) -> tuple[bool, str]:
    """model is 'provider:name' — return (key-is-set, provider)."""
    provider, _, _ = model.partition(":")
    env_var = _PROVIDER_KEY_ENV.get(provider)
    return bool(env_var and os.getenv(env_var)), provider


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness check: ffprobe on PATH + a provider key set for each configured model."""
    import shutil

    ffprobe_ok = shutil.which("ffprobe") is not None
    perception_ok, perception_provider = _provider_ok(PERCEPTION_MODEL)
    compile_ok, compile_provider = _provider_ok(COMPILE_MODEL)
    ready = ffprobe_ok and perception_ok and compile_ok

    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "unready",
            "ffprobe": ffprobe_ok,
            "perception_model": {"model": PERCEPTION_MODEL, "provider_key_set": perception_ok},
            "compile_model": {"model": COMPILE_MODEL, "provider_key_set": compile_ok},
            "max_video_s": MAX_VIDEO_S,
        },
    )


def _run_inspection_sync(video_path: str, session_type: str) -> InspectionReport:
    return run_inspection(video_path, session_type=session_type)


@app.post("/inspect")
async def inspect_endpoint(
    session_type: Literal["move_in", "move_out"] = Form(...),
    video: UploadFile = File(...),
) -> JSONResponse:
    """Run the brain pipeline on an uploaded walkthrough video.

    The video is written to a scratch temp file only for the duration of the pipeline run,
    then always deleted — raw video is never persisted, per the PRD.
    """
    started = time.perf_counter()
    suffix = Path(video.filename or "").suffix or ".mp4"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(await video.read())
            tmp_path = tmp.name

        report = await asyncio.to_thread(_run_inspection_sync, tmp_path, session_type)
        logger.info(
            'route=/inspect status=ok latency_ms=%d session_type=%s',
            (time.perf_counter() - started) * 1000,
            session_type,
        )
        return JSONResponse(content=report.model_dump())
    except VideoValidationError as exc:
        logger.info("route=/inspect status=rejected detail=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface failures cleanly
        logger.exception("route=/inspect status=error")
        raise HTTPException(status_code=500, detail=f"pipeline failed: {type(exc).__name__}") from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))  # noqa: S104
