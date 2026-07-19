"""Service health checks — is each external dependency online?

The BI Analyst Agent talks to several backends, most of which have in-memory fallbacks
(see project/config.py). This module probes each one and reports a simple status so the UI
(and, later, a /health endpoint) can show what's actually wired and reachable.

Three states per service:
    online    — configured AND reachable right now
    offline   — configured but the probe failed (bad creds / down / network)
    disabled  — not configured; the app is using its in-memory/local fallback

Every probe is defensive: short timeouts, and any exception => "offline" (never raises), so
calling check_services() can't break the caller. Lazy imports keep this module cheap to load
and avoid hard deps on optional clients.
"""

from __future__ import annotations

from dataclasses import dataclass

ONLINE = "online"
OFFLINE = "offline"
DISABLED = "disabled"


@dataclass
class ServiceHealth:
    key: str        # stable id, e.g. "bigquery"
    label: str      # display name, e.g. "BigQuery"
    status: str     # online | offline | disabled
    detail: str     # short context (target host, fallback note, or error)


def _short(exc: Exception, n: int = 60) -> str:
    line = (str(exc).strip().splitlines() or [""])[0] or type(exc).__name__
    return line if len(line) <= n else line[: n - 1] + "…"


# ── per-service probes (each returns (status, detail)) ───────────────
def _check_bigquery() -> tuple[str, str]:
    from project.config import (
        BIGQUERY_DATASET,
        BIGQUERY_PROJECT,
        USE_BIGQUERY,
        bq_credentials,
    )

    if not USE_BIGQUERY:
        return DISABLED, "using local SQLite"
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=BIGQUERY_PROJECT, credentials=bq_credentials())
        client.query("SELECT 1").result(timeout=10)
        return ONLINE, f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}"
    except Exception as exc:  # noqa: BLE001 — any failure is "offline"
        return OFFLINE, _short(exc)


def _check_qdrant() -> tuple[str, str]:
    from project.config import QDRANT_API_KEY, QDRANT_URL, USE_QDRANT

    if not USE_QDRANT:
        return DISABLED, "in-memory retrieval"
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=5)
        client.get_collections()
        return ONLINE, QDRANT_URL
    except Exception as exc:  # noqa: BLE001
        return OFFLINE, _short(exc)


def _check_redis() -> tuple[str, str]:
    from project.config import REDIS_URL, USE_REDIS

    if not USE_REDIS:
        return DISABLED, "in-memory"
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3).ping()
        return ONLINE, REDIS_URL.rsplit("@", 1)[-1]  # hide any user:pass
    except Exception as exc:  # noqa: BLE001
        return OFFLINE, _short(exc)


def _check_langsmith() -> tuple[str, str]:
    from project.config import LANGSMITH_API_KEY

    if not LANGSMITH_API_KEY:
        return DISABLED, "tracing off"
    try:
        import httpx

        # /info is a lightweight reachability check on the LangSmith API.
        resp = httpx.get(
            "https://api.smith.langchain.com/info",
            headers={"x-api-key": LANGSMITH_API_KEY},
            timeout=5,
        )
        if resp.status_code < 500:
            return ONLINE, "api.smith.langchain.com"
        return OFFLINE, f"HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return OFFLINE, _short(exc)


_PROBES = [
    ("bigquery", "BigQuery", _check_bigquery),
    ("qdrant", "Qdrant", _check_qdrant),
    ("redis", "Redis", _check_redis),
    ("langsmith", "LangSmith", _check_langsmith),
]


def check_services() -> list[ServiceHealth]:
    """Probe every service and return their health. Never raises."""
    out: list[ServiceHealth] = []
    for key, label, probe in _PROBES:
        try:
            status, detail = probe()
        except Exception as exc:  # noqa: BLE001 — belt-and-suspenders; probes already guard
            status, detail = OFFLINE, _short(exc)
        out.append(ServiceHealth(key=key, label=label, status=status, detail=detail))
    return out


if __name__ == "__main__":
    icon = {ONLINE: "online ", OFFLINE: "offline", DISABLED: "off    "}
    for s in check_services():
        print(f"[{icon[s.status]}] {s.label:10} {s.detail}")
