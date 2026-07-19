"""Unit tests for per-thread conversation history (project/memory/history.py)."""

from __future__ import annotations

from project.memory import append_turn, clear_history, recent_turns, render_context
from project.memory.history import _MAX_TURNS


def test_append_and_recent_oldest_to_newest():
    clear_history("t1")
    append_turn("t1", "q1", "a1")
    append_turn("t1", "q2", "a2")
    assert recent_turns("t1", 5) == [("q1", "a1"), ("q2", "a2")]
    assert recent_turns("t1", 1) == [("q2", "a2")]  # just the latest


def test_render_context_empty_without_history():
    clear_history("none")
    assert render_context("none") == ""
    assert render_context("") == ""  # no thread id


def test_render_context_includes_turns_and_framing():
    clear_history("t2")
    append_turn("t2", "What's the revenue like?", "Net revenue is $1.4M.")
    ctx = render_context("t2")
    assert "What's the revenue like?" in ctx
    assert "1.4M" in ctx
    assert "resolve references" in ctx.lower()  # framed for follow-ups, not re-answering


def test_history_rolls_old_turns_into_summary(monkeypatch):
    # Older turns are COMPRESSED into a rolling summary (not dropped). Mock the summarizer so the
    # test stays offline — it just needs to fire when the thread grows past the budget.
    import project.memory.history as h

    monkeypatch.setattr(h, "summarize_turns", lambda turns, prior="": f"[summary of {len(turns)} older turns]")

    clear_history("t3")
    for i in range(_MAX_TURNS + 5):
        append_turn("t3", f"q{i}", f"a{i}")

    raw = recent_turns("t3", 100)
    assert len(raw) <= _MAX_TURNS                                    # raw turns stay bounded
    assert raw[-1] == (f"q{_MAX_TURNS + 4}", f"a{_MAX_TURNS + 4}")   # newest kept verbatim
    ctx = render_context("t3")
    assert "summary of" in ctx.lower()                              # older turns summarized, not dropped


def test_no_thread_id_is_a_noop():
    append_turn("", "q", "a")  # must not raise
    assert recent_turns("") == []
