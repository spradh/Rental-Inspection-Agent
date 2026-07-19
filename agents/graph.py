"""The multi-agent graph — a LangGraph StateGraph for the Loom & Co. BI analyst.

This is the **Investigate** capability: a *"why"* question is decomposed into
sub-investigations across BI specialists, then synthesized into a root-cause
`AnalystAnswer` with ranked recommendations.

Topology:
    supervisor --(route)--> a specialist --> supervisor --> ... --> synthesize
The supervisor reads the question + what's been gathered, routes to the right specialist
(or decides it has enough), with a hop cap so a multi-step investigation can fan across
several specialists before answering. `synthesize` emits a STRUCTURED, validated
`AnalystAnswer` (project.schemas), repairing once on a ValidationError.

Public API:
    build_graph()                 -> a compiled LangGraph runnable (with a checkpointer)
    ask(question, *, role, ...)   -> AnalystAnswer   (the MAIN entrypoint: guard + memory + graph)
    AnalystState                  -> the shared graph-state TypedDict

This module makes no LLM/network calls on import. A demo lives under __main__.

Run:
    python -m project.agents.graph
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from project.config import SUPERVISOR_MODEL, SYNTH_MODEL
from project.memory import (
    append_turn,
    apply_profile,
    learn_from_query,
    load_profile,
    make_checkpointer,
    render_context,
)
from project.schemas import AnalystAnswer, ChartSpec
from project.security import guard, reset_role, set_role
from shared.llm import chat

from project.agents.specialists import SPECIALISTS

# Safety cap so a confused supervisor can't loop forever. An investigation may legitimately
# visit several specialists, so allow one more hop than there are specialists.
MAX_SPECIALIST_HOPS = len(SPECIALISTS) + 1


# ── shared graph state ─────────────────────────────────────────────────────────
def _merge(left: dict, right: dict) -> dict:
    return {**left, **right}


class AnalystState(TypedDict):
    """Typed state every node reads/updates. `gathered` accumulates specialist output."""

    question: str
    role: str
    gathered: Annotated[dict[str, str], _merge]  # specialist name -> findings
    next: str  # routing decision: a specialist name or "synthesize"
    hops: int  # how many specialists we've run (loop guard)
    answer: Optional[AnalystAnswer]
    system_extra: str  # personalization/preamble folded into prompts (may be "")
    chart: Optional[dict]  # a ChartSpec dict if a specialist drew one (last write wins)
    convo: str  # recent conversation history, for resolving follow-ups (may be "")


# ── helpers ────────────────────────────────────────────────────────────────────
def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _extract_sql(gathered: dict[str, str]) -> list[str]:
    """Pull any SQL strings out of the specialists' findings (best-effort)."""
    sql: list[str] = []
    for text in gathered.values():
        for line in text.splitlines():
            stripped = line.strip().strip("`")
            low = stripped.lower()
            if low.startswith("select ") or low.startswith("with "):
                if stripped not in sql:
                    sql.append(stripped)
    return sql


def _extract_citations(gathered: dict[str, str]) -> list[str]:
    """Pull KB/metric citations (e.g. [data/docs/metric-definitions.md]) from findings."""
    import re

    cites: list[str] = []
    for text in gathered.values():
        for match in re.findall(r"\[([^\[\]]+?\.md[^\[\]]*)\]", text):
            c = match.strip()
            if c and c not in cites:
                cites.append(c)
    return cites


# ── nodes ──────────────────────────────────────────────────────────────────────
def supervisor(state: AnalystState) -> dict:
    """Route to the next specialist for this investigation, or to synthesis."""
    done = list(state["gathered"].keys())
    remaining = [k for k in SPECIALISTS if k not in done]

    # Force synthesis once every specialist has run or we hit the hop cap — don't rely on
    # the model to notice it's out of useful routes.
    if not remaining or state.get("hops", 0) >= MAX_SPECIALIST_HOPS:
        return {"next": "synthesize"}

    gathered_summary = (
        "\n".join(f"  [{k}] {v[:200]}" for k, v in state["gathered"].items()) or "  nothing yet"
    )
    convo = state.get("convo") or ""
    routing_prompt = (
        "You are the supervisor of a Loom & Co. BI analyst team. The analyst's question might "
        "be a metric or ranking ('which customers ordered the most?'), a 'why' (root cause), or "
        "a follow-up ('now chart that'). Route it to the specialist best placed to answer. The "
        "specialists can query the FULL warehouse via SQL (tables: customers, products, orders, "
        "order_items, returns, web_sessions, marketing_campaigns, inventory), so ANY data "
        "question can be answered by a specialist — pick the closest domain. Use the "
        "conversation below to resolve follow-ups.\n\n"
        + (convo + "\n\n" if convo else "")
        + "Specialists still available:\n"
        + "\n".join(f"- {k}: {SPECIALISTS[k].description}" for k in remaining)
        + "\nReply 'synthesize' ONLY once enough has been gathered to write the answer — never "
        "as the first step, since there is nothing to synthesize from yet.\n\n"
        "IMPORTANT: a chart/plot/visualization is produced ONLY by a specialist running the "
        "plot tool, never at synthesis. If the current question asks to chart/plot/visualize/"
        "graph something (even as a follow-up), you MUST route to a data specialist (sales, "
        "marketing, or product).\n\n"
        f"Current question: {state['question']}\n"
        f"Gathered so far:\n{gathered_summary}\n\n"
        "Reply with ONLY one route key (a specialist key or 'synthesize')."
    )
    choice = chat(
        routing_prompt, model=SUPERVISOR_MODEL, system=state.get("system_extra") or None
    ).strip().lower()

    # Guard against unknown routes or re-running a specialist already in `gathered`.
    if choice not in remaining:
        choice = "synthesize"
    # A question that passed the security guard needs data: never synthesize from an EMPTY
    # gather. If the model bailed to 'synthesize' before any specialist ran, route to the
    # general analyst so at least one specialist actually queries the warehouse.
    if choice == "synthesize" and not done:
        choice = "sales" if "sales" in remaining else remaining[0]
    return {"next": choice}


def run_specialist(state: AnalystState) -> dict:
    """Run whichever specialist the supervisor selected; write findings (and any chart) to state."""
    key = state["next"]
    findings, chart = SPECIALISTS[key].run(state["question"], context=state.get("convo") or "")
    out: dict = {"gathered": {key: findings}, "hops": state.get("hops", 0) + 1}
    if chart:
        out["chart"] = chart
    return out


def synthesize(state: AnalystState) -> dict:
    """Combine gathered findings into a STRUCTURED, root-cause AnalystAnswer."""
    gathered = state["gathered"]
    context = "\n\n".join(f"[{k}]\n{v}" for k, v in gathered.items())
    convo = state.get("convo") or ""
    # The chart is attached by code from the plot tool — NOT authored by the model. Hide it
    # from the synth schema, else the model tries to emit the data array (huge, often truncated
    # → invalid JSON) and re-invents numbers instead of grounding them.
    schema_dict = AnalystAnswer.model_json_schema()
    schema_dict.get("properties", {}).pop("chart", None)
    schema = json.dumps(schema_dict)
    extra = state.get("system_extra") or ""
    base_prompt = (
        "You are the lead Loom & Co. BI analyst. Synthesize the specialists' findings into a "
        "ROOT-CAUSE answer to the question, then give ranked, actionable recommendations. "
        "Keep the prose `answer` concise: at most 5 sentences.\n\n"
        "Return a single JSON object matching this schema (no prose, no code fences). Fill "
        "`evidence` with the specific figures the answer rests on, and set `confidence` "
        "(0-1) honestly. Do NOT include a 'chart' field — any chart is attached automatically.\n"
        "Values shown as '[redacted]' are intentionally masked by the data-access policy for "
        "this caller's role — they are NOT missing data. Answer using the visible figures, and "
        "if the question asked for a redacted field, note it is restricted by policy. NEVER "
        "claim 'no data is available' when findings were provided.\n"
        f"{schema}\n\n"
        + (convo + "\n\n" if convo else "")
        + f"Current question: {state['question']}\n\n"
        f"Findings from specialists:\n{context or 'none'}"
    )

    # Prompt for JSON, validate against the schema, and repair once on failure. If it still
    # won't parse, degrade gracefully (a plain answer) rather than crash the whole request.
    raw = chat(base_prompt, model=SYNTH_MODEL, system=extra or None)
    try:
        answer = AnalystAnswer.model_validate_json(_strip_fences(raw))
    except ValidationError as e:
        repair = (
            f"{base_prompt}\n\nYour previous reply was invalid:\n{raw}\n\n"
            f"It failed validation with:\n{e}\nReturn ONLY corrected JSON."
        )
        raw = chat(repair, model=SYNTH_MODEL, system=extra or None)
        try:
            answer = AnalystAnswer.model_validate_json(_strip_fences(raw))
        except ValidationError:
            answer = AnalystAnswer(
                answer="I gathered the data but couldn't format a structured answer this time. "
                "Please retry or rephrase.",
                confidence=0.0,
            )

    # Backfill provenance from the gathered tool output the model may not have echoed.
    for sql in _extract_sql(gathered):
        if sql not in answer.sql_used:
            answer.sql_used.append(sql)
    for cite in _extract_citations(gathered):
        if cite not in answer.citations:
            answer.citations.append(cite)

    # Attach any chart a specialist drew (built from real rows by the plot tool).
    if state.get("chart"):
        try:
            answer.chart = ChartSpec.model_validate(state["chart"])
        except ValidationError:
            answer.chart = None
    return {"answer": answer}


# ── routing edge: supervisor's decision -> next node ───────────────────────────
def route(state: AnalystState) -> str:
    """Conditional edge: map state['next'] to a node name or synthesis."""
    return "specialist" if state["next"] in SPECIALISTS else "synthesize"


def build_graph():
    """Wire nodes + edges and compile WITH a checkpointer from make_checkpointer()."""
    g = StateGraph(AnalystState)
    g.add_node("supervisor", supervisor)
    g.add_node("specialist", run_specialist)
    g.add_node("synthesize", synthesize)

    g.set_entry_point("supervisor")
    g.add_conditional_edges(
        "supervisor", route, {"specialist": "specialist", "synthesize": "synthesize"}
    )
    g.add_edge("specialist", "supervisor")  # back to the supervisor for the next route
    g.add_edge("synthesize", END)
    return g.compile(checkpointer=make_checkpointer())


def _refusal(reason: str) -> AnalystAnswer:
    """A safe AnalystAnswer returned when the security guard blocks a request."""
    return AnalystAnswer(
        answer=(
            "This request was blocked by the security policy and cannot be answered: "
            f"{reason}"
        ),
        evidence=[],
        recommendations=["Rephrase the request within policy, or contact a data admin."],
        sql_used=[],
        citations=["data/docs/data-access-policy.md"],
        confidence=0.0,
    )


def ask(
    question: str,
    *,
    role: str = "analyst",
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AnalystAnswer:
    """Main entrypoint: guard the request, apply memory, run the graph, return an answer.

    1. `guard()` runs first — on a block, returns an AnalystAnswer explaining the refusal.
    2. If `user_id` is given, load + apply that analyst's UserProfile (personalize prompts)
       and `learn_from_query` from the (clean) question.
    3. Invoke the compiled graph on a FRESH checkpoint thread — each question is one complete
       investigation, so its working state (gathered/hops) must not bleed into the next turn.
       Cross-turn continuity comes from `convo` (render_context) + append_turn, not the checkpoint.
    """
    verdict = guard(question or "", role=role)
    if not verdict["ok"]:
        return _refusal(verdict["reason"])

    clean_question = verdict["clean_question"]

    system_extra = ""
    if user_id:
        profile = load_profile(user_id)
        profile = learn_from_query(profile, clean_question)
        system_extra = apply_profile(profile, "You are the Loom & Co. BI analyst.")

    # Short-term memory: recent turns on this thread, so follow-ups ("now chart that", "why?")
    # resolve against what was just asked. Working state stays fresh each turn; only the
    # rendered conversation is fed into the prompts.
    convo = render_context(thread_id) if thread_id else ""

    graph = build_graph()
    initial: AnalystState = {
        "question": clean_question,
        "role": verdict["role"],
        "gathered": {},
        "next": "",
        "hops": 0,
        "answer": None,
        "system_extra": system_extra,
        "chart": None,
        "convo": convo,
    }
    # Each ask() is ONE complete investigation (supervisor -> ... -> synthesize). Its graph
    # state (gathered/hops/answer) is per-QUESTION, so the checkpointer gets a FRESH thread
    # every call. Reusing the caller's thread_id would reload the prior question's `gathered`
    # — and its `_merge` reducer means an empty input can't clear it — so the supervisor would
    # see every specialist "already run" and skip straight to synthesis (no specialist runs on
    # a follow-up). Cross-turn continuity is carried by `convo` (render_context) + append_turn
    # below, keyed on the caller's thread_id — not by this checkpoint.
    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    # Stamp the caller's role for the duration of the run so the data tools (run_sql) redact
    # columns this role may not see (PII, cost/margin). Out-of-band so the model can't spoof it.
    role_token = set_role(verdict["role"])
    try:
        out = graph.invoke(initial, config=config)
    finally:
        reset_role(role_token)
    answer = out.get("answer")
    if answer is None:  # extremely defensive — synthesize always sets it
        answer = AnalystAnswer(answer="No answer was produced for this question.", confidence=0.0)

    # Record this turn so the NEXT question on this thread has context.
    if thread_id:
        append_turn(thread_id, clean_question, answer.answer)
    return answer


if __name__ == "__main__":
    q = "Why did West-region conversion drop last quarter?"
    result = ask(q)
    print(f"Q: {q}\n")
    print(result.model_dump_json(indent=2))
