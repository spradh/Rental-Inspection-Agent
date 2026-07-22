"""Security package for the BI Analyst Agent.

Enforces Loom & Co.'s data-access-policy.md in code:
    redact_pii       -> mask structured PII (+ optional NER) on inputs and outputs
    detect_injection -> layered heuristics (+ optional fail-closed LLM classifier)
    check_access     -> deny-by-default RBAC mapping roles to data sources
    audit_log        -> append-only JSONL trail with provenance (PII-redacted)
    guard            -> combined pre-flight middleware the API/agent calls per request
"""

from __future__ import annotations

from .audit import AuditRecord, audit_log, make_record, read_all
from .context import get_role, reset_role, set_role
from .injection import Verdict, detect_injection, screen
from .middleware import guard
from .pii import Finding, redact_pii, redact_request, redact_response
from .rbac import (
    AccessDecision,
    allowed_sources,
    authorize,
    check_access,
    filter_sources,
    restricted_columns,
)

__all__ = [
    # pii
    "redact_pii",
    "redact_request",
    "redact_response",
    "Finding",
    # injection
    "detect_injection",
    "screen",
    "Verdict",
    # rbac
    "check_access",
    "allowed_sources",
    "authorize",
    "filter_sources",
    "restricted_columns",
    "AccessDecision",
    # request-scoped role (RBAC/PII enforcement channel)
    "set_role",
    "get_role",
    "reset_role",
    # audit
    "audit_log",
    "make_record",
    "read_all",
    "AuditRecord",
    # middleware
    "guard",
]
