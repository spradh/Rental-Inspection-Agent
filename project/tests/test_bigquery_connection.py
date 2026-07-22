"""Opt-in LIVE test: can we actually connect to BigQuery with the configured credentials?

Skipped by default (it needs a real GCP project, credentials, and network — and runs a
tiny billable query). Enable when BigQuery is configured in .env and:

    RUN_BQ_TESTS=1 uv run pytest project/tests/test_bigquery_connection.py -v

It reads the REAL BIGQUERY_PROJECT/DATASET from .env directly, because the offline conftest
forces BIGQUERY_PROJECT="" to keep the rest of the suite on SQLite. Credentials resolve via
project.config.bq_credentials() (the GOOGLE_CREDENTIALS_B64 base64 key, or gcloud ADC).
"""

from __future__ import annotations

import os
import pathlib

import pytest
from dotenv import dotenv_values

ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENV = dotenv_values(ROOT / ".env")
PROJECT = os.getenv("BIGQUERY_PROJECT") or _ENV.get("BIGQUERY_PROJECT")
DATASET = os.getenv("BIGQUERY_DATASET") or _ENV.get("BIGQUERY_DATASET") or "loomco"

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BQ_TESTS") != "1" or not PROJECT,
    reason="set RUN_BQ_TESTS=1 with BigQuery configured in .env to run the live connection test",
)


def _client():
    from google.cloud import bigquery

    from project.config import bq_credentials

    return bigquery.Client(project=PROJECT, credentials=bq_credentials())


def test_can_connect_and_query_bigquery():
    """Authenticate + run a trivial query — proves credentials + connectivity work."""
    rows = list(_client().query("SELECT 1 AS ok").result())
    assert rows[0]["ok"] == 1


def test_warehouse_dataset_is_reachable():
    """The Loom dataset is loaded and queryable with these credentials' permissions."""
    sql = f"SELECT COUNT(*) AS n FROM `{PROJECT}.{DATASET}.orders`"
    n = list(_client().query(sql).result())[0]["n"]
    assert n > 0, f"{PROJECT}.{DATASET}.orders is empty — run `python -m data.load_bigquery`"
