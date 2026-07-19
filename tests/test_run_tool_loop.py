"""Unit tests for shared.llm.run_tool_loop — the multi-provider native tool-calling loop.

The provider SDKs are fully mocked, so these assert our loop logic for BOTH dialects:
it executes the tool the model asks for, feeds the observation back, stops on the final
turn, and returns (final_text, executed_calls) with faithful provenance.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.llm import run_tool_loop

TOOLS = [{"name": "run_sql", "description": "run sql",
          "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}}}]


def _recorder():
    seen = []

    def execute(name, args):
        seen.append((name, args))
        return "obs:42"

    return seen, execute


# ── OpenAI-compatible (OpenRouter / OpenAI) dialect ──────────────────
class _OAMsg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in self.tool_calls]
        return d


def _oa_toolcall(cid, name, arguments):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=arguments))


def _oa_resp(msg):
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _make_fake_openai(responses):
    seq = iter(responses)

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(seq)))

    return _FakeOpenAI


def test_openrouter_executes_tool_then_finishes(monkeypatch):
    import openai

    responses = [
        _oa_resp(_OAMsg(tool_calls=[_oa_toolcall("c1", "run_sql", '{"sql": "SELECT 1"}')])),
        _oa_resp(_OAMsg(content="The result is 42.")),
    ]
    monkeypatch.setattr(openai, "OpenAI", _make_fake_openai(responses))
    seen, execute = _recorder()

    text, calls = run_tool_loop(
        model="openrouter:qwen/qwen3-32b", system="s", user="u", tools=TOOLS, execute=execute
    )

    assert text == "The result is 42."
    assert seen == [("run_sql", {"sql": "SELECT 1"})]
    assert calls == [{"name": "run_sql", "args": {"sql": "SELECT 1"}, "result": "obs:42"}]


# ── Anthropic dialect ────────────────────────────────────────────────
def _anthropic_resp(stop_reason, blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


def _make_fake_anthropic(responses):
    seq = iter(responses)

    class _FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = SimpleNamespace(create=lambda **kw: next(seq))

    return _FakeAnthropic


def test_anthropic_executes_tool_then_finishes(monkeypatch):
    import anthropic

    responses = [
        _anthropic_resp("tool_use", [SimpleNamespace(type="tool_use", id="t1", name="run_sql", input={"sql": "SELECT 1"})]),
        _anthropic_resp("end_turn", [SimpleNamespace(type="text", text="The result is 42.")]),
    ]
    monkeypatch.setattr(anthropic, "Anthropic", _make_fake_anthropic(responses))
    seen, execute = _recorder()

    text, calls = run_tool_loop(
        model="anthropic:claude-haiku-4-5", system="s", user="u", tools=TOOLS, execute=execute
    )

    assert text == "The result is 42."
    assert seen == [("run_sql", {"sql": "SELECT 1"})]
    assert calls == [{"name": "run_sql", "args": {"sql": "SELECT 1"}, "result": "obs:42"}]


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        run_tool_loop(model="bogus:model", system="s", user="u", tools=TOOLS, execute=lambda n, a: "x")
