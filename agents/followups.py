"""LLM-generated follow-up question suggestions for the Ask UI.

Given the question just asked and the analyst's answer, propose a few short, clickable
follow-up questions the user might ask next. Uses the cheap specialist model and is fully
defensive — any failure returns [] so the UI simply shows no chips.
"""

from __future__ import annotations

from project.config import SPECIALIST_MODEL
from shared.llm import chat

_PROMPT = (
    "You suggest follow-up questions for a Loom & Co. business-analytics chat. Given the user's "
    "question and the analyst's answer, propose {n} SHORT follow-up questions the user might ask "
    "next. Rules: each is a standalone question (<= 9 words), specific to this topic, answerable "
    "from the sales/marketing/product/customer data (a metric, trend, breakdown, chart, a 'why', "
    "or a 'what should we do'). One per line, no numbering, no preamble.\n\n"
    "User question: {question}\nAnalyst answer: {answer}\n\nFollow-ups:"
)


def suggest_followups(question: str, answer: str, n: int = 3) -> list[str]:
    """Return up to `n` short follow-up questions, or [] on empty input / any failure."""
    if not (question and answer and answer.strip()):
        return []
    try:
        raw = chat(
            _PROMPT.format(n=n, question=question, answer=answer[:1200]),
            model=SPECIALIST_MODEL,
            max_tokens=160,
        )
    except Exception:  # noqa: BLE001 — suggestions are best-effort; never break the chat
        return []

    out: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        q = line.strip().lstrip("0123456789.-)•*").strip().strip('"').strip()
        if len(q) >= 4 and "?" in q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:n]
