"""Loom & Co. — BI Analyst Workbench (Streamlit).

The product UI for the BI Analyst Agent reference implementation. Two tabs:

  * Workbench — the autonomous "Monday review": KPI/anomaly cards, a revenue
    forecast chart, and a one-click written review.
  * Ask — a chat box over the agent, rendering the structured AnalystAnswer.

Run from the repo root:

    streamlit run project/streamlit/app.py

The agent is never called at import time — only inside Streamlit callbacks /
tab render — so this module imports cleanly.
"""

from __future__ import annotations

import random
import sys
import uuid
from pathlib import Path

# Make `project` importable when Streamlit runs this file directly.
# project/streamlit/app.py -> project/streamlit -> project -> repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from project.agents import ask, suggest_followups, weekly_review_data
from project.config import SUPERVISOR_MODEL
from project.dashboard import dashboard_data

# ── Page setup ───────────────────────────────────────────────────────
st.set_page_config(page_title="Loom & Co. — BI Analyst Workbench", layout="wide")
st.title("Loom & Co. — BI Analyst Workbench")

ROLES = ["analyst", "data_admin", "marketing_viewer"]

# Pool of starter prompts; 3 are shown at random in the Ask panel when the thread is empty.
_SUGGESTION_POOL = [
    "What was net revenue in March 2026?",
    "Why did West-region conversion drop?",
    "Plot monthly net revenue",
    "Which subcategory has the highest return rate?",
    "What needs reordering right now?",
    "Which customers ordered the most?",
    "What's our gross margin this quarter?",
    "Which acquisition channel has the worst repeat rate?",
    "Show revenue by category",
    "Forecast net revenue for the next 3 months",
]

# Severity → a color for the anomaly cards.
_SEVERITY_COLOR = {
    "high": "#e74c3c",
    "medium": "#f39c12",
    "low": "#2ecc71",
}


# ── Helpers ──────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Running the weekly review…")
def _cached_weekly_review(months_ahead: int = 3) -> dict:
    """Cache the deterministic weekly-review data (no LLM call)."""
    return weekly_review_data(months_ahead=months_ahead)


@st.cache_data(ttl=120, show_spinner="Loading dashboard…")
def _cached_dashboard() -> dict:
    """Cache the warehouse KPIs + chart series (no LLM call)."""
    return dashboard_data()


def _series_df(rows: list[dict], index: str, value: str | None = None):
    """rows (list[dict]) -> DataFrame indexed by `index` for st.*_chart, or None if empty."""
    if not rows:
        return None
    df = pd.DataFrame(rows).set_index(index)
    return df[[value]] if value else df


def _ensure_session_state() -> None:
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = f"st-{uuid.uuid4().hex[:12]}"
    if "chat" not in st.session_state:
        st.session_state.chat = []  # list[dict]: {"question": str, "answer": AnalystAnswer}


# ── Sidebar ──────────────────────────────────────────────────────────
_STATUS_ICON = {"online": "🟢", "offline": "🔴", "disabled": "⚪"}


@st.cache_data(ttl=30, show_spinner=False)
def _service_status() -> list[tuple[str, str, str]]:
    """Probe services (cached 30s so we don't re-ping on every rerun)."""
    from project.health import check_services

    return [(s.label, s.status, s.detail) for s in check_services()]


def _render_services() -> None:
    st.subheader("Services")
    st.caption("🟢 online · 🔴 offline · ⚪ off (using fallback)")
    for label, st_status, detail in _service_status():
        st.markdown(
            f"{_STATUS_ICON.get(st_status, '⚪')} **{label}** "
            f"<span style='color:gray;font-size:0.85em'>· {detail}</span>",
            unsafe_allow_html=True,
        )
    if st.button("↻ Refresh", key="refresh_services", use_container_width=True):
        _service_status.clear()
        st.rerun()


def _render_sidebar() -> str:
    with st.sidebar:
        st.header("Settings")
        role = st.selectbox("Role", ROLES, index=0)
        st.caption(f"Model · {SUPERVISOR_MODEL.split(':', 1)[-1]}")
        st.divider()
        _render_services()
        st.caption("First query loads the embedding models (slow once, then warm).")
    return role


# ── Markdown safety ──────────────────────────────────────────────────
def _md(text) -> str:
    """Escape `$` so Streamlit's KaTeX doesn't render dollar amounts as math.

    `st.markdown` treats `$…$` as LaTeX, so a memo like "$71K to $198K" gets mangled into
    math. Escaping each `$` to `\\$` renders a literal dollar sign. Apply to all MODEL-/
    DATA-generated text we hand to st.markdown / st.write / st.caption.
    """
    return str(text).replace("$", "\\$")


def _render_chart(chart) -> None:
    """Render a ChartSpec (model or dict) next to the prose. Built from real query rows."""
    if chart is None:
        return
    spec = chart.model_dump() if hasattr(chart, "model_dump") else dict(chart)
    x = spec.get("x") or []
    # Keep only series whose length matches the x-axis (defensive against malformed specs).
    data = {s["name"]: s["values"] for s in (spec.get("series") or []) if len(s.get("values", [])) == len(x)}
    if not x or not data:
        return
    if spec.get("title"):
        st.markdown(f"**{_md(spec['title'])}**")
    df = pd.DataFrame(data, index=x)
    ctype = spec.get("type", "bar")
    {"line": st.line_chart, "area": st.area_chart}.get(ctype, st.bar_chart)(df)


# ── Workbench tab ────────────────────────────────────────────────────
def _render_anomaly_card(a: dict) -> None:
    severity = str(a.get("severity", "medium")).lower()
    color = _SEVERITY_COLOR.get(severity, "#7f8c8d")
    metric = a.get("metric", "(metric)")
    finding = a.get("finding", "")
    evidence = a.get("evidence", "")
    recommendation = a.get("recommendation", "")

    with st.container(border=True):
        st.markdown(
            f"<span style='background:{color};color:white;padding:2px 8px;"
            f"border-radius:6px;font-size:0.75rem;font-weight:600;'>"
            f"{severity.upper()}</span> &nbsp; <strong>{metric}</strong>",
            unsafe_allow_html=True,
        )
        if finding:
            st.write(_md(finding))
        if evidence:
            st.caption(f"Evidence: {_md(evidence)}")
        if recommendation:
            st.markdown(f"**Recommendation:** {_md(recommendation)}")


def _render_dashboard() -> None:
    """KPI tiles + a grid of charts over the warehouse (no LLM, no forecast)."""
    try:
        dash = _cached_dashboard()
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the UI
        st.error(f"Could not load the dashboard: {exc}")
        return

    kpis = dash.get("kpis", [])
    # Tile the KPIs 3-per-row so they stay readable in the dashboard column.
    for i in range(0, len(kpis), 3):
        chunk = kpis[i:i + 3]
        for k, col in zip(chunk, st.columns(len(chunk))):
            col.metric(k["label"], k["value"], k.get("delta"))

    ch = dash.get("charts", {})

    def _chart(title, key, index, value, kind="bar"):
        st.caption(title)
        df = _series_df(ch.get(key, []), index, value)
        if df is None:
            st.info("No data.")
            return
        {"bar": st.bar_chart, "line": st.line_chart, "area": st.area_chart}[kind](df)

    st.markdown("##### Trends")
    a, b = st.columns(2)
    with a:
        _chart("Net revenue by month", "revenue_by_month", "month", "net_revenue", "area")
    with b:
        _chart("Conversion rate by month (%)", "conversion_by_month", "month", "conversion_%", "line")

    st.markdown("##### Breakdowns")
    a, b = st.columns(2)
    with a:
        _chart("Revenue by category", "revenue_by_category", "category", "revenue")
    with b:
        _chart("Net revenue by region", "revenue_by_region", "region", "net_revenue")
    a, b = st.columns(2)
    with a:
        _chart("Return rate by subcategory (%)", "return_rate_by_subcategory", "subcategory", "return_rate_pct")
    with b:
        _chart("Top products by revenue", "top_products", "product", "revenue")

    _chart("Marketing spend by channel", "marketing_spend_by_channel", "channel", "spend")


def _render_workbench(role: str) -> None:
    st.subheader("Business Dashboard")
    st.caption("Live KPIs and charts over the Loom & Co. warehouse, plus the autonomous review.")

    _render_dashboard()

    st.divider()
    st.markdown("#### Anomaly watch")
    try:
        anomalies = (_cached_weekly_review().get("anomalies") or [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not run the anomaly watch: {exc}")
        anomalies = []
    if not anomalies:
        st.success("No anomalies detected against the recent baseline.")
    else:
        cols = st.columns(min(3, len(anomalies)))
        for i, a in enumerate(anomalies):
            with cols[i % len(cols)]:
                _render_anomaly_card(a)


# ── Ask tab ──────────────────────────────────────────────────────────
def _render_answer(ans) -> None:
    """Render an AnalystAnswer (or a dict with the same fields)."""
    get = (lambda k, d=None: ans.get(k, d)) if isinstance(ans, dict) else (
        lambda k, d=None: getattr(ans, k, d)
    )

    st.markdown(_md(get("answer", "") or "_(no answer)_"))
    _render_chart(get("chart"))

    confidence = get("confidence")
    if confidence is not None:
        st.caption(f"Confidence: {float(confidence):.0%}")

    recommendations = get("recommendations", []) or []
    if recommendations:
        with st.expander(f"Recommendations ({len(recommendations)})"):
            for r in recommendations:
                st.markdown(f"- {_md(r)}")

    evidence = get("evidence", []) or []
    if evidence:
        with st.expander(f"Evidence ({len(evidence)})"):
            for e in evidence:
                st.markdown(f"- {_md(e)}")

    citations = get("citations", []) or []
    if citations:
        with st.expander(f"Citations ({len(citations)})"):
            for c in citations:
                st.markdown(f"- {_md(c)}")

    sql_used = get("sql_used", []) or []
    if sql_used:
        with st.expander(f"SQL used ({len(sql_used)})"):
            for q in sql_used:
                st.code(q, language="sql")


def _render_ask(role: str) -> None:
    st.subheader("Ask the analyst")
    st.caption(f"Role: **{role}** · thread: `{st.session_state.thread_id}`")

    # The message history is a fixed-height SCROLL box, so a long thread scrolls within the
    # panel instead of growing the page (the input below stays put). Populated after the input
    # is drawn so the input is always visible, even while a reply computes.
    history = st.container(height=_ASK_HISTORY_HEIGHT, border=False)
    question = st.chat_input("Ask a question about the business…")
    if question:
        st.session_state.chat.append({"question": question, "answer": None})

    with history:
        # Empty thread: show 3 random clickable starter prompts. Clicking one submits it like a
        # typed question (append + rerun -> the loop below computes the answer).
        if not st.session_state.chat:
            st.markdown("**Try a question:**")
            starters = st.session_state.setdefault("starters", random.sample(_SUGGESTION_POOL, 3))
            for i, suggestion in enumerate(starters):
                if st.button(suggestion, key=f"start_{i}", use_container_width=True):
                    st.session_state.chat.append({"question": suggestion, "answer": None})
                    st.rerun()

        for turn in st.session_state.chat:
            with st.chat_message("user"):
                st.markdown(_md(turn["question"]))
            with st.chat_message("assistant"):
                if turn["answer"] is None:  # the turn just submitted — compute it now
                    with st.spinner("Thinking…"):
                        try:
                            turn["answer"] = ask(
                                turn["question"], role=role, thread_id=st.session_state.thread_id
                            )
                        except Exception as exc:  # noqa: BLE001
                            turn["answer"] = {"answer": f"The agent failed: {exc}", "confidence": 0.0}
                        ans = turn["answer"]
                        ans_text = ans.get("answer") if isinstance(ans, dict) else getattr(ans, "answer", "")
                        turn["followups"] = suggest_followups(turn["question"], ans_text)
                _render_answer(turn["answer"])

        # LLM-generated, context-aware follow-up chips after the latest answer (resolve against
        # the conversation thread via memory). Computed once per turn and cached on the turn.
        if st.session_state.chat:
            followups = st.session_state.chat[-1].get("followups") or []
            for i, followup in enumerate(followups):
                if st.button(followup, key=f"followup_{len(st.session_state.chat)}_{i}", use_container_width=True):
                    st.session_state.chat.append({"question": followup, "answer": None})
                    st.rerun()


# ── Main ─────────────────────────────────────────────────────────────
_PANEL_HEIGHT = 820          # fixed height so each column scrolls independently
_ASK_HISTORY_HEIGHT = 650    # message scroll area (leaves room for header + input)

# Give the Ask panel its own background (targets the keyed container's DOM class).
_ASK_PANEL_CSS = """
<style>
.st-key-ask_panel {
    background-color: #1b2230;
    border: 1px solid #2b3346;
    border-radius: 10px;
    padding: 1rem 1rem 0.25rem 1rem;
}
</style>
"""


def main() -> None:
    _ensure_session_state()
    role = _render_sidebar()
    st.markdown(_ASK_PANEL_CSS, unsafe_allow_html=True)

    # Dashboard is the main view; Ask is a side panel beside it (no tabs). Each lives in a
    # fixed-height container so they scroll INDEPENDENTLY — a long chat never buries the dashboard.
    dashboard_col, ask_col = st.columns([2, 1], gap="large")
    with dashboard_col, st.container(height=_PANEL_HEIGHT, border=False):
        _render_workbench(role)
    with ask_col, st.container(key="ask_panel"):
        _render_ask(role)


main()
