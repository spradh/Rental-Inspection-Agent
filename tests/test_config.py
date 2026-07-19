"""Offline unit tests for config helpers — specifically bq_credentials() decode logic.

No network: these assert the GOOGLE_CREDENTIALS_B64 handling deterministically. The live
'can we actually reach BigQuery' check lives in test_bigquery_connection.py (opt-in).
"""

from __future__ import annotations

import base64
import json

import pytest

from project.config import bq_credentials


def test_bq_credentials_none_when_unset(monkeypatch):
    monkeypatch.delenv("GOOGLE_CREDENTIALS_B64", raising=False)
    assert bq_credentials() is None  # -> bigquery.Client falls back to default ADC chain


def test_bq_credentials_raises_on_malformed_blob(monkeypatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", "this-is-not-valid-base64-json")
    with pytest.raises(Exception):  # noqa: B017 — base64/JSON decode failure, surfaced loudly
        bq_credentials()


def test_bq_credentials_decodes_and_reaches_key_validation(monkeypatch):
    """A well-formed (but fake-key) SA JSON decodes + parses and reaches credential build.

    It fails only at RSA key validation — proving the base64 -> JSON -> from_service_account_info
    path is wired, without needing a real key or network.
    """
    info = {
        "type": "service_account",
        "project_id": "x",
        "private_key_id": "x",
        "private_key": "-----BEGIN PRIVATE KEY-----\nbroken\n-----END PRIVATE KEY-----\n",
        "client_email": "a@b.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", base64.b64encode(json.dumps(info).encode()).decode())
    with pytest.raises(Exception):  # noqa: B017 — fails at key validation, not decode/parse
        bq_credentials()
