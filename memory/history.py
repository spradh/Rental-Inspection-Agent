"""Conversation history per thread — the agent's short-term memory of the dialog.

Lets a follow-up question ("give me the chart", "why?", "break that down by region") resolve
against what was just asked, instead of being treated as a standalone question with no subject.

Bounded memory that DOESN'T just forget: the last few turns are kept verbatim, and older turns
are folded into a **rolling summary** once a thread grows past its budget (rather than being
dropped). So a long conversation stays cheap to inject while early context is still remembered,
compressed. In-memory by default (dev / single process); swap for a Redis-backed store without
touching the agent graph — the graph only calls `render_context` and `append_turn`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from project.memory.summarize import summarize_turns

# Keep this many recent turns VERBATIM (they carry the detail follow-ups need: "that", "those").
_KEEP_RAW = 3
# Roll older turns into the summary once the raw turns exceed EITHER budget (count or ~tokens).
_MAX_TURNS = 6
_TOKEN_BUDGET = 1500


@dataclass
class _Thread:
    turns: list[tuple[str, str]] = field(default_factory=list)  # raw, un-summarized turns
    summary: str = ""                                           # rolling summary of older turns


_STORE: dict[str, _Thread] = {}


def _turn_tokens(turns: list[tuple[str, str]]) -> int:
    """Rough token estimate (~4 chars/token) — good enough to decide when to summarize."""
    return sum(len(q) + len(a) for q, a in turns) // 4


def append_turn(thread_id: str, question: str, answer: str) -> None:
    """Record one completed (question, answer) turn; roll older turns into the summary if big."""
    if not thread_id:
        return
    t = _STORE.setdefault(thread_id, _Thread())
    t.turns.append((question, answer))

    # Over budget (too many turns, or too many tokens)? Fold all but the last _KEEP_RAW into the
    # running summary. Best-effort: if the summarizer call fails, drop the head anyway so memory
    # stays bounded (the old behavior) rather than growing without limit.
    if len(t.turns) > _KEEP_RAW and (len(t.turns) > _MAX_TURNS or _turn_tokens(t.turns) > _TOKEN_BUDGET):
        head, t.turns = t.turns[:-_KEEP_RAW], t.turns[-_KEEP_RAW:]
        try:
            t.summary = summarize_turns(head, t.summary)
        except Exception:  # noqa: BLE001 — summarization is best-effort; never break the turn
            pass


def recent_turns(thread_id: str, n: int = 3) -> list[tuple[str, str]]:
    """Return the last `n` raw (question, answer) turns for a thread (oldest→newest)."""
    t = _STORE.get(thread_id)
    return t.turns[-n:] if t else []


def render_context(thread_id: str, n: int = 3, max_answer_chars: int = 400) -> str:
    """Render the running summary + recent raw turns as a prompt block, or '' if no history.

    Framed so the model uses it ONLY to resolve references in the current question (e.g. "the
    chart", "that", "why") — not to re-answer earlier turns.
    """
    t = _STORE.get(thread_id)
    if not t or (not t.turns and not t.summary):
        return ""
    lines = [
        "Recent conversation (use ONLY to resolve references in the current question — e.g. "
        '"the chart", "why", "that number"; do not re-answer earlier turns):'
    ]
    if t.summary:
        lines.append(f"Summary of earlier turns: {t.summary}")
    for question, answer in t.turns[-n:]:
        lines.append(f'- Analyst asked: "{question}"')
        lines.append(f'  You answered: "{answer[:max_answer_chars]}"')
    return "\n".join(lines)


def clear(thread_id: str) -> None:
    """Forget a thread's history (e.g. a 'new chat' action)."""
    _STORE.pop(thread_id, None)
