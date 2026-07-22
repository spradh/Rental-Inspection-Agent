"""Unit tests for LLM-generated follow-up suggestions (the LLM is mocked)."""

from __future__ import annotations

import project.agents.followups as fu


def test_parses_clean_questions(monkeypatch):
    monkeypatch.setattr(
        fu, "chat",
        lambda *a, **k: "1. What about by region?\n- Why did it drop?\nIs margin affected?\nnot a question",
    )
    out = fu.suggest_followups("q", "a")
    assert out == ["What about by region?", "Why did it drop?", "Is margin affected?"]


def test_caps_at_n(monkeypatch):
    monkeypatch.setattr(fu, "chat", lambda *a, **k: "\n".join(f"Question {i}?" for i in range(10)))
    assert len(fu.suggest_followups("q", "a", n=2)) == 2


def test_dedupes_case_insensitively(monkeypatch):
    monkeypatch.setattr(fu, "chat", lambda *a, **k: "Why?\nwhy?\nWhat now?")
    assert fu.suggest_followups("q", "a") == ["Why?", "What now?"]


def test_empty_when_answer_blank():
    assert fu.suggest_followups("q", "") == []


def test_empty_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(fu, "chat", boom)
    assert fu.suggest_followups("q", "an answer") == []
