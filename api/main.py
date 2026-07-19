"""FastAPI service for the BI Analyst Agent — async, JSON, health check.

Production entrypoint for the reference implementation. The agent already exists in
`project.agents`; this layer just exposes it over HTTP. `ask()` is atomic (returns a full
AnalystAnswer), and /chat returns it as a single JSON response — no streaming.

Deployed on Cloud Run, this service runs on **cloud backends only**: BigQuery (warehouse),
Qdrant (vector store / retrieval), Redis (memory), LangSmith (tracing), and an LLM provider
(OpenRouter). /health probes every one and returns 503 unless they're all online — so a deploy
that's missing a service (env key) or can't reach one is held out of rotation.

Endpoints:
    GET  /health   -> readiness probe: 503 unless a provider key is set AND every cloud service
                      (BigQuery, Qdrant, Redis, LangSmith) is online.
    POST /chat      -> run ask(...) and return the AnalystAnswer as JSON.
    GET  /report    -> generate_report() as text/plain.

Run locally (from repo root):
    uvicorn project.api.main:app --reload
    curl -s -X POST localhost:8000/chat -H 'content-type: application/json' \
        -d '{"question":"What were top SKUs last month?"}'
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from project.agents import ask, generate_report
from project.health import ONLINE, check_services

# ── Structured logging ───────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("bi-analyst")

app = FastAPI(title="BI Analyst Agent", version="1.0.0")

_PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")


class ChatRequest(BaseModel):
    question: str
    role: str = "analyst"
    thread_id: str | None = None
    user_id: str | None = None


def _run_ask(req: ChatRequest):
    """Sync helper so the whole ask() call (including its kwargs) runs in one thread."""
    return ask(
        req.question,
        role=req.role,
        thread_id=req.thread_id,
        user_id=req.user_id,
    )


@app.post("/chat")
async def chat_endpoint(req: ChatRequest) -> Response:
    """Run the agent and return the full AnalystAnswer as JSON."""
    started = time.perf_counter()
    try:
        answer = await asyncio.to_thread(_run_ask, req)
        logger.info(
            'route=/chat status=ok latency_ms=%d thread_id=%s',
            (time.perf_counter() - started) * 1000,
            req.thread_id,
        )
        return Response(content=answer.model_dump_json(), media_type="application/json")
    except Exception as exc:  # noqa: BLE001 — surface failures cleanly
        logger.exception("route=/chat status=error")
        return Response(
            content=json.dumps({"error": f"agent failed: {type(exc).__name__}"}),
            media_type="application/json",
            status_code=500,
        )


@app.get("/report", response_class=PlainTextResponse)
async def report_endpoint() -> Response:
    """Return the autonomous weekly-review narrative as plain text."""
    try:
        text = await asyncio.to_thread(generate_report)
        return PlainTextResponse(content=text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("route=/report status=error")
        return PlainTextResponse(
            content=f"report failed: {type(exc).__name__}",
            status_code=500,
        )


# Path is `/health`, NOT `/healthz`: Google's frontend reserves the exact path `/healthz` on
# *.run.app and 404s it before it reaches the container. `/health` is fine.
@app.get("/health")
async def health(response: Response) -> dict:
    """Readiness check: a provider key AND every cloud backend online.

    Probes BigQuery, Qdrant, Redis, and LangSmith (`project.health.check_services`) plus the LLM
    provider key, and returns **503 unless the provider key is set and every service is ONLINE**.
    So a deploy that's missing a service (env key unset → the probe reports "disabled") or can't
    reach one ("offline") is held out of rotation until it's actually wired for all cloud
    dependencies. The probes do network I/O, so they run off the event loop.
    """
    services = await asyncio.to_thread(check_services)
    provider_ok = any(os.getenv(k) for k in _PROVIDER_KEYS)
    ready = provider_ok and all(s.status == ONLINE for s in services)
    if not ready:
        response.status_code = 503
    return {
        "status": "ok" if ready else "unready",
        "provider": provider_ok,
        "services": {s.key: {"status": s.status, "detail": s.detail} for s in services},
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))  # noqa: S104
