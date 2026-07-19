"""PII redaction — detect and mask sensitive data before it reaches the model,
the provider, or the logs.

Ported from the Week 6 security solution (pii_redaction.py). We redact in BOTH
directions (OWASP LLM02 Sensitive Information Disclosure):
    request  -> redact before the query hits the model/provider and the audit log
    response -> redact before the answer reaches the user and the logs

Detection is layered on purpose:
    regex -> high precision on structured PII (email, phone, SSN, credit card, IBAN)
    NER   -> needed for free-text PII (names, locations, orgs) — optional, Presidio

Neither alone is enough; regex misses names, NER misses formats. The NER layer is
import-guarded so the package works with zero extra deps; install Presidio to enable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# name -> compiled pattern. High-precision structured PII.
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "PHONE": re.compile(r"\b(?:\+?1[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}\b"),
    # IBAN — 2-letter country code, 2 check digits, up to 30 alnum.
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
}

# NER entity labels (Presidio) we treat as PII, mapped to our mask names.
_NER_ENTITIES = {
    "PERSON": "PERSON",
    "LOCATION": "LOCATION",
    "NRP": "PERSON",  # nationality / religious / political group
    "ORGANIZATION": "ORG",
}


@dataclass
class Finding:
    """One detected PII span."""

    entity: str  # e.g. "EMAIL"
    text: str  # the matched substring
    start: int
    end: int


def detect(text: str) -> list[Finding]:
    """Return all PII spans found by the regex layer, sorted left-to-right."""
    findings: list[Finding] = []
    for entity, pattern in PII_PATTERNS.items():
        for m in pattern.finditer(text):
            findings.append(Finding(entity, m.group(), m.start(), m.end()))
    return sorted(findings, key=lambda f: f.start)


# Lazily built once, then reused. None until first attempted; False if unavailable.
_ANALYZER = None


def _get_analyzer():
    """Return a cached Presidio AnalyzerEngine, or None if Presidio isn't installed."""
    global _ANALYZER
    if _ANALYZER is None:
        try:
            from presidio_analyzer import AnalyzerEngine

            _ANALYZER = AnalyzerEngine()
        except Exception:  # noqa: BLE001 — any import/setup failure => disable NER
            _ANALYZER = False
    return _ANALYZER or None


def detect_ner(text: str) -> list[Finding]:
    """Optional NER layer for free-text PII (PERSON, LOCATION, ORG).

    Uses Microsoft Presidio if installed; otherwise returns [] so the regex layer
    still works with zero extra dependencies.
    """
    analyzer = _get_analyzer()
    if analyzer is None:
        return []
    findings: list[Finding] = []
    for r in analyzer.analyze(text=text, language="en", entities=list(_NER_ENTITIES)):
        findings.append(
            Finding(_NER_ENTITIES[r.entity_type], text[r.start : r.end], r.start, r.end)
        )
    return findings


def _merge(findings: list[Finding]) -> list[Finding]:
    """Drop spans fully contained in an earlier (regex-preferred) span to avoid
    double-masking overlaps between the regex and NER layers."""
    kept: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.start, -(f.end - f.start))):
        if any(f.start >= k.start and f.end <= k.end for k in kept):
            continue
        kept.append(f)
    return kept


def redact_pii(text: str, *, mask: str = "[REDACTED:{entity}]") -> str:
    """Replace every detected PII span with a typed mask.

    Combines the regex and NER layers, then replaces spans RIGHT to LEFT so earlier
    offsets stay valid. The audit log should only ever see this output, never raw PII.
    Used on inputs (before the model/provider/log) and outputs (before the user/log).
    """
    if not text:
        return text
    findings = _merge(detect(text) + detect_ner(text))
    for f in sorted(findings, key=lambda f: f.start, reverse=True):
        text = text[: f.start] + mask.format(entity=f.entity) + text[f.end :]
    return text


# Direction-specific aliases, kept for clarity at call sites.
def redact_request(query: str) -> str:
    """Redact an inbound user query before it reaches the model/provider/logs."""
    return redact_pii(query)


def redact_response(answer: str) -> str:
    """Redact an outbound answer before it reaches the user/logs."""
    return redact_pii(answer)


if __name__ == "__main__":
    sample = (
        "Hi, I'm Jane Doe, email jane.doe@example.com, SSN 123-45-6789, "
        "card 4111 1111 1111 1111, IBAN DE89370400440532013000, "
        "call me at (415) 555-0199."
    )
    print("RAW:     ", sample)
    print("FINDINGS:", [(f.entity, f.text) for f in detect(sample)])
    print("REDACTED:", redact_pii(sample))
    print("NER active:", _get_analyzer() is not None)
