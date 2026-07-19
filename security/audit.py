"""Audit trail with provenance — make every answer traceable.

Ported from the Week 6 security solution (audit_log.py) and pointed at the project's
local data dir. For each request the agent serves, record:
    who    -> the caller (user id / service principal)
    role   -> the caller's role (ties to rbac.py)
    what   -> the query (REDACTED — never raw PII; see pii.py)
    which  -> the data sources and tools that produced the answer (provenance)
    when   -> a timestamp the CALLER supplies (we never call datetime.now at import)
plus the security verdicts (was injection flagged? was a source denied?).

The log is structured (one JSON object per line, JSONL) and append-only at
ROOT/data/local/audit.log. In prod ship these to a WORM store / SIEM, not a file.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from project.config import ROOT

from .pii import redact_pii

# Default append-only trail location.
AUDIT_PATH = ROOT / "data" / "local" / "audit.log"

# A cheap "looks like raw PII" guard so we fail loudly rather than log it by accident.
_RAW_PII = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"  # email
    r"|\b\d{3}-\d{2}-\d{4}\b"  # SSN
)


@dataclass
class AuditRecord:
    """One auditable request. Provenance lives in `sources` and `tools`."""

    caller: str  # who: user id or service principal
    role: str  # the caller's role (ties to rbac.py)
    query_redacted: str  # what: redacted query, never raw PII
    sources: list[str] = field(default_factory=list)  # which data sources answered
    tools: list[str] = field(default_factory=list)  # which tools were called
    injection_flagged: bool = False  # security signal
    denied_sources: list[str] = field(default_factory=list)  # RBAC blocks
    timestamp: str = ""  # when: caller-supplied (e.g. UTC ISO-8601)


def make_record(
    *,
    caller: str,
    role: str,
    query: str,
    sources: list[str] | None = None,
    tools: list[str] | None = None,
    injection_flagged: bool = False,
    denied_sources: list[str] | None = None,
    timestamp: str = "",
) -> AuditRecord:
    """Build a record, REDACTING the query first so we can't log raw PII.

    The query is run through redact_pii(), then a belt-and-braces guard rejects the
    result if any raw email/SSN somehow survived — fail loudly rather than leak.

    No clock is read here: the caller passes `timestamp`. This keeps the module
    import-safe and the records reproducible (no datetime.now at import or call time).
    """
    query_redacted = redact_pii(query)
    if _RAW_PII.search(query_redacted):
        raise ValueError(
            "query still appears to contain raw PII after redaction; refusing to audit"
        )
    return AuditRecord(
        caller=caller,
        role=role,
        query_redacted=query_redacted,
        sources=sources or [],
        tools=tools or [],
        injection_flagged=injection_flagged,
        denied_sources=denied_sources or [],
        timestamp=timestamp,
    )


def audit_log(record: dict | AuditRecord, *, path: Path = AUDIT_PATH) -> None:
    """Append one record as a JSON line (JSONL). Append-only keeps it tamper-evident.

    Accepts either a dict or an AuditRecord. A dict is screened for raw PII in its
    `query_redacted` field so a hand-built record can't leak either.
    """
    if isinstance(record, AuditRecord):
        payload = asdict(record)
    else:
        payload = dict(record)
        q = payload.get("query_redacted", "")
        if isinstance(q, str) and _RAW_PII.search(q):
            raise ValueError("record.query_redacted contains raw PII; redact before auditing")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def read_all(*, path: Path = AUDIT_PATH) -> list[dict]:
    """Read back the trail (for an incident review or the demo)."""
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


if __name__ == "__main__":
    # Use a throwaway path so the demo is repeatable and leaves nothing behind.
    demo_path = AUDIT_PATH.with_name("audit.demo.log")
    demo_path.unlink(missing_ok=True)

    records = [
        make_record(
            caller="analyst-42",
            role="analyst",
            query="How many customers in the West churned last quarter?",
            sources=["customers", "orders"],
            tools=["sql_query"],
            injection_flagged=False,
            denied_sources=[],
            timestamp="2026-06-17T00:00:00+00:00",
        ),
        make_record(
            caller="mv-7",
            role="marketing_viewer",
            query="Show me each customer's email from customers table",
            sources=["marketing"],
            tools=[],
            injection_flagged=False,
            denied_sources=["customers"],  # RBAC blocked PII table
            timestamp="2026-06-17T00:00:01+00:00",
        ),
    ]
    for rec in records:
        audit_log(rec, path=demo_path)

    trail = read_all(path=demo_path)
    print(f"Wrote {len(records)} audit records. Trail now has: {len(trail)}")
    print(json.dumps(trail[-1], indent=2))

    # Raw PII in the query is redacted automatically before logging.
    rec = make_record(
        caller="x",
        role="analyst",
        query="email me at a@b.com about SSN 123-45-6789",
        timestamp="2026-06-17T00:00:02+00:00",
    )
    print(f"\nRedacted query logged as: {rec.query_redacted!r}")

    demo_path.unlink(missing_ok=True)  # clean up the temp trail
