"""Unit tests for service health probes (project/health.py).

Offline & defensive: probes for unconfigured services report 'disabled' without touching the
network; a configured-but-unreachable service reports 'offline' without raising.
"""

from __future__ import annotations

import project.config as cfg
from project.health import DISABLED, OFFLINE, ONLINE, ServiceHealth, check_services


def test_returns_all_services_with_valid_status():
    out = check_services()
    assert [s.key for s in out] == ["bigquery", "qdrant", "redis", "langsmith"]
    for s in out:
        assert isinstance(s, ServiceHealth)
        assert s.status in {ONLINE, OFFLINE, DISABLED}
        assert s.detail, "every service should have a non-empty detail"


def test_unconfigured_service_is_disabled_not_offline():
    # conftest forces BIGQUERY_PROJECT="" -> warehouse is local SQLite -> BigQuery disabled.
    bq = {s.key: s for s in check_services()}["bigquery"]
    assert bq.status == DISABLED


def test_configured_but_unreachable_is_offline_and_never_raises(monkeypatch):
    # Point Redis at a closed port so the probe takes its error path quickly.
    monkeypatch.setattr(cfg, "USE_REDIS", True, raising=False)
    monkeypatch.setattr(cfg, "REDIS_URL", "redis://localhost:1", raising=False)
    redis_health = {s.key: s for s in check_services()}["redis"]
    assert redis_health.status == OFFLINE
