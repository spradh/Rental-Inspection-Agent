"""Native tool-calling loop, multi-provider.

`shared.llm.chat` is text-only. This adds `run_tool_loop`: a provider-agnostic native
tool-calling loop so agents work across Anthropic and OpenAI-compatible providers
(OpenRouter, OpenAI) without the brittle hand-rolled JSON-ReAct protocol.

The two providers speak different dialects — Anthropic returns `tool_use` blocks, OpenAI
returns `tool_calls` — so the message-history shapes differ. We hide that here and expose
one call:

    text, calls = run_tool_loop(
        model="anthropic:claude-haiku-4-5",          # or openrouter:qwen/... etc.
        system="...", user="...",
        tools=[{"name", "description", "input_schema"}, ...],   # Anthropic-shape schemas
        execute=lambda name, args: "<observation string>",      # runs the tool
    )

`tools` is the Anthropic schema shape (what `project.tools.tool_schemas()` already emits).
`execute(name, args)` runs the tool and returns a string observation (never raises — mirror
the registry's `dispatch`). Returns `(final_text, calls)` where `calls` is the list of
`{"name", "args", "result"}` actually executed — so callers can record faithful provenance
(e.g. the real SQL that ran).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

DEFAULT_MAX_TOKENS = 1024


def run_tool_loop(
    *,
    model: str,
    system: str,
    user: str,
    tools: list[dict],
    execute: Callable[[str, dict], str],
    max_steps: int = 6,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[str, list[dict]]:
    """Run a native tool-calling loop and return (final_text, executed_calls)."""
    provider, _, model_name = model.partition(":")
    if provider == "anthropic":
        return _anthropic_loop(model_name, system, user, tools, execute, max_steps, max_tokens)
    if provider in ("openrouter", "openai"):
        return _openai_loop(provider, model_name, system, user, tools, execute, max_steps, max_tokens)
    raise ValueError(f"Unknown provider {provider!r} in model {model!r}")


# ── Anthropic dialect: tool_use blocks ───────────────────────────────
def _anthropic_loop(model_name, system, user, tools, execute, max_steps, max_tokens):
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages: list[dict] = [{"role": "user", "content": user}]
    calls: list[dict] = []

    last_text = ""
    for _step in range(max_steps):
        resp = client.messages.create(
            model=model_name, max_tokens=max_tokens, system=system or "", tools=tools, messages=messages
        )
        messages.append({"role": "assistant", "content": resp.content})
        last_text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason != "tool_use":
            return last_text, calls

        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            args = dict(block.input)
            observation = execute(block.name, args)
            calls.append({"name": block.name, "args": args, "result": observation})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": observation})
        messages.append({"role": "user", "content": results})

    return last_text, calls


# ── OpenAI-compatible dialect (OpenRouter / OpenAI): tool_calls ───────
def _openai_loop(provider, model_name, system, user, tools, execute, max_steps, max_tokens):
    from openai import OpenAI

    client = (
        OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
        if provider == "openrouter"
        else OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    )
    oa_tools = [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    calls: list[dict] = []

    for _step in range(max_steps):
        resp = client.chat.completions.create(
            model=model_name, messages=messages, tools=oa_tools, tool_choice="auto", max_tokens=max_tokens
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))  # echo the turn back (incl. tool_calls)
        if not msg.tool_calls:
            return (msg.content or "").strip(), calls

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            observation = execute(tc.function.name, args)
            calls.append({"name": tc.function.name, "args": args, "result": observation})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})

    return "", calls
