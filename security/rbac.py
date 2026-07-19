"""RBAC for data access — the agent reads only what the CALLER is allowed to.

Ported from the Week 6 security solution (rbac.py) and bound to Loom & Co.'s
data-access-policy.md. Least privilege (OWASP LLM06 Excessive Agency): enforce
access BEFORE retrieval, not by asking the model nicely. A compromised prompt can't
grant itself access it never had — the gate sits outside the model.

    caller(role) + data_source -> allow / deny   (DENY BY DEFAULT)

Roles (from data-access-policy.md):
    analyst          -> default. Aggregated metrics across all tables; product, order,
                        session, marketing, inventory. NO raw customer PII.
    data_admin       -> everything, including customer PII.
    marketing_viewer -> marketing, web_sessions, aggregated orders. No PII; no
                        unit_cost / margin detail.

A "source" here is a warehouse table or a logical data source the agent may read.
Row-level PII redaction is handled separately (see pii.py); RBAC gates the tables.
"""

from __future__ import annotations

from dataclasses import dataclass

# The warehouse tables / logical sources the agent can read from.
ALL_SOURCES = {
    "customers",
    "products",
    "orders",
    "order_items",
    "web_sessions",
    "marketing",
    "inventory",
}

# role -> the data sources that role may read. Anything not listed is denied.
ROLE_POLICY: dict[str, set[str]] = {
    # Everything, including raw customer PII.
    "data_admin": set(ALL_SOURCES),
    # Default agent role: all tables for aggregates, but raw customer rows are
    # gated at the row level by PII redaction. RBAC still permits the table so the
    # agent can compute counts/rates over it; pii.py strips individual PII.
    "analyst": {
        "products",
        "orders",
        "order_items",
        "web_sessions",
        "marketing",
        "inventory",
        "customers",  # aggregates only; PII columns redacted downstream
    },
    # Marketing, web sessions, aggregated orders. No PII, no cost/margin tables.
    "marketing_viewer": {
        "marketing",
        "web_sessions",
        "orders",  # aggregated orders only; PII + cost/margin redacted downstream
    },
}

# PII columns that must never reach a non-admin caller (policy: customers.*).
PII_COLUMNS = {
    "customers.first_name",
    "customers.last_name",
    "customers.email",
    "customers.phone",
    "customers.street",
    "customers.city",
    "customers.postal_code",
}

# Cost / margin columns marketing_viewer must not see (policy).
RESTRICTED_COLUMNS: dict[str, set[str]] = {
    "marketing_viewer": {
        "products.unit_cost",
        "order_items.unit_cost",
        "products.margin",
        "order_items.margin",
    },
}


@dataclass
class AccessDecision:
    """Outcome of one authorization check (gets recorded in the audit log)."""

    allowed: bool
    role: str
    source: str
    reason: str


def allowed_sources(role: str) -> set[str]:
    """Return the set of sources `role` may read. Unknown role => empty set (deny)."""
    return set(ROLE_POLICY.get(role, set()))


def authorize(role: str, source: str) -> AccessDecision:
    """Decide whether `role` may read `source`. DENY BY DEFAULT.

    An unknown role maps to an empty set => denied. The reason lands in the audit trail.
    """
    if source in allowed_sources(role):
        return AccessDecision(True, role, source, "role permits source")
    return AccessDecision(
        False, role, source, f"role {role!r} not permitted to read {source!r}"
    )


def check_access(role: str, source: str) -> bool:
    """Boolean convenience: True if `role` may read `source`. Deny by default."""
    return authorize(role, source).allowed


def filter_sources(role: str, requested: list[str]) -> tuple[list[str], list[str]]:
    """Split requested sources into (allowed, denied) for one role.

    The agent retrieves only from `allowed`; `denied` goes to the audit log so an
    unexpected denial (e.g. an injection asking for a forbidden source) is visible.
    """
    allowed, denied = [], []
    for source in requested:
        (allowed if check_access(role, source) else denied).append(source)
    return allowed, denied


def restricted_columns(role: str) -> set[str]:
    """Columns this role must never see. Non-admins always lose PII columns;
    marketing_viewer additionally loses cost/margin columns."""
    if role == "data_admin":
        return set()
    cols = set(PII_COLUMNS)
    cols |= RESTRICTED_COLUMNS.get(role, set())
    return cols


if __name__ == "__main__":
    requested = ["products", "customers", "marketing", "inventory", "web_sessions"]
    for role in ("analyst", "data_admin", "marketing_viewer", "intruder"):
        allowed, denied = filter_sources(role, requested)
        print(f"{role:>17}: allow={allowed}  deny={denied}")
        print(f"{'':>17}  restricted_cols={sorted(restricted_columns(role))}")
