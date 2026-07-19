"""Central configuration for the BI Analyst Agent.

One place for model choices, data locations, and backend toggles so the rest of the
package never reads os.environ directly. Values come from the repo .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = two levels up from this file (project/config.py -> project -> repo root).
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# ── Data ─────────────────────────────────────────────────────────
DB_PATH = ROOT / "data" / "local" / "loomco.db"   # the warehouse (SQLite, local dev)
KB_DIR = ROOT / "data" / "docs"                    # the knowledge base (markdown)

# ── Warehouse backend (SQLite local ↔ BigQuery deployed) ─────────
# Set BIGQUERY_PROJECT (e.g. in the deployed env) to query BigQuery instead of SQLite.
BIGQUERY_PROJECT = os.getenv("BIGQUERY_PROJECT", "")
BIGQUERY_DATASET = os.getenv("BIGQUERY_DATASET", "loomco")
USE_BIGQUERY = bool(BIGQUERY_PROJECT)
# The model must write SQL in the active dialect (SQLite and BigQuery differ).
SQL_DIALECT = "BigQuery Standard SQL" if USE_BIGQUERY else "SQLite"

# ── Models (provider:model — resolved by shared.llm) ─────────────
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "anthropic:claude-sonnet-4-6")
SPECIALIST_MODEL = os.getenv("SPECIALIST_MODEL", "anthropic:claude-haiku-4-5")
SYNTH_MODEL = os.getenv("SYNTH_MODEL", "anthropic:claude-sonnet-4-6")

# ── Retrieval backend ────────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "loomco_kb")
# Use Qdrant only when a real (non-local) cluster is configured; else in-memory retrieval.
USE_QDRANT = bool(QDRANT_URL) and "localhost" not in QDRANT_URL and "127.0.0.1" not in QDRANT_URL
EMBED_MODEL = "multi-qa-mpnet-base-dot-v1"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ── Memory backend ───────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "")
USE_REDIS = bool(REDIS_URL) and "localhost" not in REDIS_URL and "127.0.0.1" not in REDIS_URL

# ── Observability ────────────────────────────────────────────────
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")


def status() -> str:
    """One-line summary of the active configuration (no secrets)."""
    if USE_BIGQUERY:
        warehouse = f"bigquery:{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}"
    else:
        warehouse = "sqlite" + ("" if DB_PATH.exists() else " MISSING (run: python -m data.generate)")
    return (
        f"warehouse={warehouse} | "
        f"retrieval={'qdrant' if USE_QDRANT else 'in-memory'} | "
        f"memory={'redis' if USE_REDIS else 'in-memory'} | "
        f"supervisor={SUPERVISOR_MODEL}"
    )


def bq_credentials():
    """BigQuery service-account credentials from GOOGLE_CREDENTIALS_B64, or None.

    Lets a student run against BigQuery WITHOUT `gcloud auth application-default login`:
    paste a base64-encoded service-account JSON key into GOOGLE_CREDENTIALS_B64 (in the
    gitignored .env) and it's decoded here IN MEMORY — no key file ever touches disk.

    Returns None when the var is unset, so `bigquery.Client()` falls back to the normal
    ADC chain (a GOOGLE_APPLICATION_CREDENTIALS file path, or gcloud ADC, or — on Cloud
    Run — the runtime service account). Passing credentials=None is the SDK's default.

    Encode a key once with:  base64 < sa-key.json | tr -d '\\n'
    """
    blob = os.getenv("GOOGLE_CREDENTIALS_B64", "").strip()
    if not blob:
        return None
    import base64
    import json

    from google.oauth2 import service_account

    info = json.loads(base64.b64decode(blob))
    return service_account.Credentials.from_service_account_info(info)


if __name__ == "__main__":
    print(status())
