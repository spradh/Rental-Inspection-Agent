"""SQL tool — schema-aware, read-only SELECT over the warehouse.

Backend-pluggable: **SQLite** locally (default) and **BigQuery** when `BIGQUERY_PROJECT`
is configured (e.g. in the deployed env). The agent writes the SQL; this module exposes
the deterministic, guard-railed primitives: `get_schema`, `is_read_only`, `run_sql`.

The two engines speak different SQL, so `get_schema()` prepends the active **dialect** so
the model writes the right flavor (SQLite `strftime` vs BigQuery `FORMAT_DATE`/`EXTRACT`).

Every public function returns a STRING (or, for the guard, a bool) and never raises —
errors come back as readable observations the agent can react to.

Demo:
    python -m project.tools.sql
"""

from __future__ import annotations

import sqlite3

from project.config import (
    BIGQUERY_DATASET,
    BIGQUERY_PROJECT,
    DB_PATH,
    SQL_DIALECT,
    USE_BIGQUERY,
    bq_credentials,
)

MAX_ROWS = 50                  # rows rendered before truncating (token-cheap observations)
MAX_BQ_BYTES = 2_000_000_000   # safety cap on a BigQuery scan (~2 GB)

_DIALECT_NOTE = (
    f"-- SQL dialect: {SQL_DIALECT}. Reference tables unqualified (e.g. FROM orders).\n"
    + (
        "-- BigQuery: use FORMAT_DATE/EXTRACT for dates (not strftime); order_ts is TIMESTAMP.\n"
        if USE_BIGQUERY
        else "-- SQLite: use strftime() for date parts; timestamps are TEXT.\n"
    )
)


# ── read-only guard (shared by both backends) ────────────────────
def is_read_only(sql: str) -> bool:
    """Allow only a single SELECT/WITH — no chaining, no write/DDL/PRAGMA."""
    s = sql.strip().rstrip(";").strip()
    if not s or ";" in s:
        return False
    lowered = s.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False
    banned = (
        "insert ", "update ", "delete ", "drop ", "alter ", "create ",
        "replace ", "truncate ", "attach ", "pragma ", "vacuum ", "merge ",
    )
    return not any(b in lowered for b in banned)


def _format_table(rows: list[tuple], cols: list[str]) -> str:
    if not rows:
        return "(no rows)"
    shown = rows[:MAX_ROWS]
    str_rows = [[("" if v is None else str(v)) for v in r] for r in shown]
    widths = [len(c) for c in cols]
    for r in str_rows:
        for i, cell in enumerate(r):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    sep = "-+-".join("-" * w for w in widths)
    body = "\n".join(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)) for r in str_rows)
    out = f"{header}\n{sep}\n{body}"
    if len(rows) > MAX_ROWS:
        out += f"\n... ({len(rows) - MAX_ROWS} more rows; {len(rows)} total)"
    return out


# ── BigQuery backend (lazy imports so SQLite-only envs don't need the client) ──
def _bq_rows(sql: str) -> tuple[list[tuple], list[str]]:
    from google.cloud import bigquery

    client = bigquery.Client(project=BIGQUERY_PROJECT, credentials=bq_credentials())
    job_config = bigquery.QueryJobConfig(
        default_dataset=f"{BIGQUERY_PROJECT}.{BIGQUERY_DATASET}",  # unqualified table names work
        maximum_bytes_billed=MAX_BQ_BYTES,
        use_query_cache=True,
    )
    result = client.query(sql, job_config=job_config).result()
    cols = [f.name for f in result.schema]
    rows = [tuple(row.values()) for row in result]
    return rows, cols


# ── SQLite backend ───────────────────────────────────────────────
def _sqlite_rows(sql: str) -> tuple[list[tuple], list[str]]:
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
    finally:
        con.close()
    return rows, cols


# ── public API (backend-agnostic) ────────────────────────────────
def get_schema() -> str:
    """Return the warehouse schema (with a leading dialect note for the model)."""
    try:
        if USE_BIGQUERY:
            rows, _ = _bq_rows(
                "SELECT table_name, column_name, data_type "
                "FROM INFORMATION_SCHEMA.COLUMNS ORDER BY table_name, ordinal_position"
            )
            tables: dict[str, list[str]] = {}
            for tname, col, dtype in rows:
                tables.setdefault(tname, []).append(f"{col} {dtype}")
            body = "\n\n".join(f"TABLE {t} ({', '.join(cols)})" for t, cols in tables.items())
        else:
            con = sqlite3.connect(DB_PATH)
            try:
                rows = con.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            finally:
                con.close()
            body = "\n\n".join(r[0] for r in rows if r[0])
    except Exception as e:  # noqa: BLE001
        return f"SchemaError: {e}"
    return _DIALECT_NOTE + "\n" + body


def _redact_for_role(rows: list[tuple], cols: list[str]) -> list[tuple]:
    """Mask columns the current caller's role may not see (PII, and cost/margin for some roles).

    Reads the request-scoped role (set by ask()); when none is set (direct tool use), nothing
    is redacted. Matches by bare column name, so `email`, `customers.email`, or an aliased
    `c.email AS email` are all caught at the result level — no SQL parsing required.
    """
    from project.security import get_role, restricted_columns

    role = get_role()
    if not role:
        return rows
    restricted = {c.rsplit(".", 1)[-1] for c in restricted_columns(role)}
    if not restricted:
        return rows  # e.g. data_admin
    idx = [i for i, c in enumerate(cols) if c in restricted]
    if not idx:
        return rows
    return [tuple("[redacted]" if i in idx else v for i, v in enumerate(row)) for row in rows]


def run_sql(sql: str) -> str:
    """Execute a read-only SELECT against the active backend; return a text table or error."""
    if not isinstance(sql, str) or not sql.strip():
        return "SQLError: empty query."
    if not is_read_only(sql):
        return f"Refused: only a single read-only SELECT is allowed. Got: {sql.strip()[:200]}"
    try:
        rows, cols = _bq_rows(sql) if USE_BIGQUERY else _sqlite_rows(sql)
    except Exception as e:  # noqa: BLE001
        return f"SQLError: {e}"
    return _format_table(_redact_for_role(rows, cols), cols)


def query_rows(sql: str) -> list[tuple] | str:
    """Internal helper for other tools: raw rows, or an error string. Same guard as run_sql."""
    if not is_read_only(sql):
        return f"Refused non-read-only SQL: {sql.strip()[:200]}"
    try:
        rows, _ = _bq_rows(sql) if USE_BIGQUERY else _sqlite_rows(sql)
        return rows
    except Exception as e:  # noqa: BLE001
        return f"SQLError: {e}"


def query_table(sql: str) -> tuple[list[tuple], list[str]] | str:
    """Internal helper: (rows, column_names) for a read-only SELECT, or an error string.

    Like query_rows but keeps the column names — used by the chart tool to label axes/series.
    """
    if not is_read_only(sql):
        return f"Refused non-read-only SQL: {sql.strip()[:200]}"
    try:
        rows, cols = _bq_rows(sql) if USE_BIGQUERY else _sqlite_rows(sql)
        return _redact_for_role(rows, cols), cols
    except Exception as e:  # noqa: BLE001
        return f"SQLError: {e}"


if __name__ == "__main__":
    print(f"backend: {'BigQuery' if USE_BIGQUERY else 'SQLite'} | dialect: {SQL_DIALECT}\n")
    print(get_schema()[:400], "...\n")
    print("select ok:", is_read_only("SELECT 1"),
          "| drop blocked:", not is_read_only("DROP TABLE customers"))
    print(run_sql("SELECT COUNT(*) AS n_customers FROM customers"))
