"""A tiny multi-provider LLM client.

One interface over three providers so the rest of the course doesn't care which
model it's talking to. Models are addressed as ``"<provider>:<model>"``:

    openai:gpt-4o-mini
    anthropic:claude-sonnet-4-6
    openrouter:meta-llama/llama-3.3-70b-instruct

We expand this in later weeks (streaming, tool calls, prompt caching, model
cascading). For now it does one thing well: send messages, get text back.

Run a smoke test:
    python -m shared.llm.client
"""

from __future__ import annotations

import contextvars
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "anthropic:claude-sonnet-4-6")

# Per-request cap, in seconds. Generous for a chat completion, but bounded — see the note in
# _openai_compatible: without this a single stalled request hangs for 30 minutes.
REQUEST_TIMEOUT = 90.0
MAX_RETRIES = 3

Message = dict[str, str]  # {"role": "user"|"system"|"assistant", "content": "..."}

# ── Cost / latency metering (opt-in) ─────────────────────────────
# When a `cost_meter()` block is active, OpenRouter calls request usage accounting and accumulate
# the real dollar cost, latency, and call count into the meter dict. Off by default (zero overhead).
_cost_meter: contextvars.ContextVar = contextvars.ContextVar("_llm_cost_meter", default=None)


@contextmanager
def cost_meter():
    """Accumulate OpenRouter $cost + latency + call count over the calls inside the block.

        with cost_meter() as m:
            chat("...", model="openrouter:...")
        print(m["cost"], m["calls"], m["latency"])

    Only OpenRouter calls report a dollar cost (we set usage.include on them); other providers
    still count toward `calls` and `latency`. Nesting uses the innermost meter.
    """
    m = {"cost": 0.0, "calls": 0, "latency": 0.0}
    token = _cost_meter.set(m)
    try:
        yield m
    finally:
        _cost_meter.reset(token)


@dataclass
class LLMClient:
    """Routes chat requests to the right provider based on the model prefix."""

    default_model: str = DEFAULT_MODEL

    def chat(
        self,
        prompt_or_messages: str | list[Message],
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        model = model or self.default_model
        provider, _, model_name = model.partition(":")
        messages = self._normalize(prompt_or_messages)
        # Accept a "system" role inside the messages list (natural for ReAct-style
        # code) and route it to the top-level system prompt — OpenAI tolerates a
        # system message, but Anthropic rejects it and requires the `system` param.
        system, messages = self._merge_system(system, messages)

        if provider in ("openai", "openrouter"):
            return self._openai_compatible(provider, model_name, messages, system, temperature, max_tokens)
        if provider == "anthropic":
            return self._anthropic(model_name, messages, system, temperature, max_tokens)
        raise ValueError(f"Unknown provider {provider!r} in model {model!r}")

    # ── providers ────────────────────────────────────────────────
    def _openai_compatible(self, provider, model_name, messages, system, temperature, max_tokens) -> str:
        from openai import OpenAI

        # Always set an explicit timeout. The SDK defaults to 600s with 2 retries, so ONE stalled
        # request blocks for 30 minutes before it even raises — long enough to look like a hang, not
        # an error. A per-request cap that fails fast and retries is what you want in a loop.
        if provider == "openrouter":
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ["OPENROUTER_API_KEY"],
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
            )
        else:
            client = OpenAI(
                api_key=os.environ["OPENAI_API_KEY"],
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
            )

        if system:
            messages = [{"role": "system", "content": system}, *messages]

        meter = _cost_meter.get()
        kwargs: dict = {}
        if meter is not None and provider == "openrouter":
            kwargs["extra_body"] = {"usage": {"include": True}}  # ask OpenRouter for the real $ cost

        started = time.perf_counter()
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if meter is not None:
            meter["calls"] += 1
            meter["latency"] += time.perf_counter() - started
            usage = getattr(resp, "usage", None)
            if usage is not None:
                cost = getattr(usage, "cost", None) or (getattr(usage, "model_extra", None) or {}).get("cost")
                meter["cost"] += float(cost or 0.0)
        return resp.choices[0].message.content or ""

    def _anthropic(self, model_name, messages, system, temperature, max_tokens) -> str:
        from anthropic import Anthropic

        client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=REQUEST_TIMEOUT,
            max_retries=MAX_RETRIES,
        )
        resp = client.messages.create(
            model=model_name,
            system=system or "",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    @staticmethod
    def _normalize(prompt_or_messages: str | list[Message]) -> list[Message]:
        if isinstance(prompt_or_messages, str):
            return [{"role": "user", "content": prompt_or_messages}]
        return prompt_or_messages

    @staticmethod
    def _merge_system(system: str | None, messages: list[Message]) -> tuple[str | None, list[Message]]:
        """Pull any 'system' role messages out of the list and fold them into `system`."""
        parts = [system] if system else []
        parts += [m["content"] for m in messages if m.get("role") == "system"]
        convo = [m for m in messages if m.get("role") != "system"]
        return ("\n\n".join(parts) or None), convo


# Module-level convenience so simple scripts can `from shared.llm import chat`.
_default_client = LLMClient()


def chat(prompt_or_messages: str | list[Message], **kwargs) -> str:
    return _default_client.chat(prompt_or_messages, **kwargs)


if __name__ == "__main__":
    print(f"Default model: {DEFAULT_MODEL}")
    print(chat("Reply with exactly: 'LLM client is wired up.'"))
