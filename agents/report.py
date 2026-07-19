"""The autonomous "Monday Workbench" weekly review — the Watch + narrate capability.

`generate_report()` runs the deterministic anomaly checks and a revenue forecast, then
asks the LLM to weave them into a leadership-ready narrative: what changed, the likely
root cause, and a ranked set of recommendations. `weekly_review_data()` returns the same
raw pieces (anomalies + forecast points) as plain dicts for the Streamlit UI to render.

The data-gathering steps hit the local warehouse (no external services); only the final
narrative composition calls the LLM. This module makes no LLM/network calls on import.

Run:
    python -m project.agents.report
"""

from __future__ import annotations

from project.config import SYNTH_MODEL
from project.schemas import Anomaly
from project.tools.anomalies import detect_anomalies
from project.tools.forecast import forecast_net_revenue
from shared.llm import chat

# How far ahead the weekly review projects revenue.
_FORECAST_MONTHS = 3


def _forecast_points(months_ahead: int = _FORECAST_MONTHS) -> list[dict]:
    """Recent actuals + the next N forecast months as plain dicts (UI-friendly)."""
    pts = forecast_net_revenue(months_ahead)
    tail = pts[-(months_ahead + 6):]  # ~6 months of context + the forecast horizon
    return [{"month": p.month, "value": float(p.value), "kind": p.kind} for p in tail]


def _anomalies_payload(anomalies: list[Anomaly]) -> list[dict]:
    """Serialize anomalies for the UI / for the narrative prompt."""
    return [a.model_dump() for a in anomalies]


def _strip_code_fences(text: str) -> str:
    """Unwrap a whole-report ```...``` fence some models add.

    The prompt asks for Markdown, and models often return it wrapped in a ```markdown ... ```
    block. Rendered with st.markdown that shows as a literal code block, so we drop the outer
    fence (only when the text *starts* with one) and return the inner Markdown.
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()[1:]  # drop the opening ``` / ```markdown line
    if lines and lines[-1].lstrip().startswith("```"):
        lines = lines[:-1]  # drop the closing fence
    return "\n".join(lines).strip()


def weekly_review_data(months_ahead: int = _FORECAST_MONTHS) -> dict:
    """Raw pieces for the Streamlit weekly-review UI: anomalies + forecast points.

    Returns:
        {
          "anomalies":      list[dict],   # each: metric, finding, severity, evidence, recommendation
          "forecast":       list[dict],   # each: month, value, kind ("actual"|"forecast")
          "forecast_months": int,
        }
    No LLM call — this is pure data the UI can chart and table.
    """
    anomalies = detect_anomalies()
    return {
        "anomalies": _anomalies_payload(anomalies),
        "forecast": _forecast_points(months_ahead),
        "forecast_months": months_ahead,
    }


def _render_anomalies(anomalies: list[Anomaly]) -> str:
    if not anomalies:
        return "No anomalies detected against the prior period."
    lines = []
    for i, a in enumerate(anomalies, 1):
        lines.append(
            f"{i}. [{a.severity.upper()}] {a.metric}\n"
            f"   Finding: {a.finding}\n"
            f"   Evidence: {a.evidence}\n"
            f"   Suggested action: {a.recommendation}"
        )
    return "\n".join(lines)


def _render_forecast(points: list[dict]) -> str:
    return "\n".join(
        f"  {p['month']}  {p['value']:>14,.0f}  {p['kind']}" for p in points
    )


def generate_report(months_ahead: int = _FORECAST_MONTHS) -> str:
    """Compose the autonomous weekly review as a narrative string.

    Gathers anomalies (Watch) + a revenue forecast deterministically, then asks the LLM to
    write a leadership-ready memo: a headline, what changed with root-cause reasoning, the
    revenue outlook, and a ranked list of recommendations. Returns the narrative text.
    """
    anomalies = detect_anomalies()
    points = _forecast_points(months_ahead)

    prompt = (
        "You are the lead Loom & Co. BI analyst writing the Monday morning weekly review for "
        "the leadership team. Using ONLY the data below, write a concise, executive-ready memo "
        "in Markdown with these sections:\n"
        "  1. Headline — one line on the single most important thing.\n"
        "  2. What changed — walk through each anomaly, with the likely ROOT CAUSE.\n"
        "  3. Revenue outlook — read the forecast (note direction vs recent actuals).\n"
        "  4. Recommendations — a RANKED, numbered list of specific, actionable next steps "
        "tied to the findings.\n\n"
        "Do not invent numbers; cite the figures provided. Be direct and brief.\n\n"
        f"=== Anomalies (Watch checks vs prior period) ===\n{_render_anomalies(anomalies)}\n\n"
        f"=== Net revenue (recent actuals + {months_ahead}-month forecast) ===\n"
        f"{_render_forecast(points)}\n"
    )
    return _strip_code_fences(chat(prompt, model=SYNTH_MODEL, max_tokens=2048))


if __name__ == "__main__":
    print("=== weekly_review_data() ===")
    data = weekly_review_data()
    print(f"anomalies: {len(data['anomalies'])}, forecast points: {len(data['forecast'])}\n")
    print("=== generate_report() ===")
    print(generate_report())
