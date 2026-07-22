"""Request-scoped caller role — the out-of-band channel RBAC/PII enforcement reads.

The caller's role MUST NOT be a tool argument: the model controls tool args, so it could set
its own role and escalate. Instead `ask()` stamps the role here for the duration of the
request, and the data tools (`run_sql`) read it to redact columns the role may not see.

A ContextVar is per-context/thread, so concurrent callers never see each other's role, and it
propagates down the synchronous call stack (ask -> graph -> specialist -> run_sql). When no
role is set (direct tool use: data scripts, evals, tests) nothing is redacted.
"""

from __future__ import annotations

import contextvars

_request_role: contextvars.ContextVar[str] = contextvars.ContextVar("request_role", default="")


def set_role(role: str) -> contextvars.Token:
    """Set the caller role for this request; returns a token for reset_role()."""
    return _request_role.set(role or "")


def get_role() -> str:
    """The caller role for the current request, or '' if none is set (no redaction)."""
    return _request_role.get()


def reset_role(token: contextvars.Token) -> None:
    """Restore the previous role (pair with set_role in a try/finally)."""
    _request_role.reset(token)
