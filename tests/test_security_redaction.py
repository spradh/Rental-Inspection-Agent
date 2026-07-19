"""Role-aware redaction on query results (RBAC/PII), against the real SQLite warehouse.

The caller's role is set out-of-band (project.security.set_role) — never a tool arg — and
run_sql masks columns that role may not see. Proves an analyst can't pull customer PII while
data_admin can, and that direct tool use (no role) is unrestricted.
"""

from __future__ import annotations

from project.security import reset_role, set_role
from project.tools.sql import run_sql

PII_SQL = "SELECT customer_id, email FROM customers ORDER BY customer_id LIMIT 1"
COST_SQL = "SELECT product_id, unit_cost FROM products ORDER BY product_id LIMIT 1"


def _as(role: str, sql: str) -> str:
    token = set_role(role)
    try:
        return run_sql(sql)
    finally:
        reset_role(token)


def test_analyst_pii_is_redacted():
    out = _as("analyst", PII_SQL)
    assert "[redacted]" in out
    assert "@" not in out  # no email leaked


def test_data_admin_sees_pii():
    out = _as("data_admin", PII_SQL)
    assert "@" in out  # email visible
    assert "[redacted]" not in out


def test_no_role_set_is_unrestricted():
    # Direct tool use (data scripts, evals, tests) sets no role -> nothing redacted.
    assert "@" in run_sql(PII_SQL)


def test_marketing_viewer_loses_cost_but_analyst_keeps_it():
    assert "[redacted]" not in _as("analyst", COST_SQL)        # analyst may see cost/margin
    assert "[redacted]" in _as("marketing_viewer", COST_SQL)   # marketing_viewer may not


def test_marketing_viewer_also_loses_pii():
    assert "[redacted]" in _as("marketing_viewer", PII_SQL)
