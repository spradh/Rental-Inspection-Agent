"""Multi-provider LLM client for the cohort.

Public surface:
    from shared.llm import chat, LLMClient          # text-only chat
    from shared.llm import run_tool_loop            # native tool-calling loop (multi-provider)
    from shared.llm import cost_meter               # accumulate OpenRouter $cost + latency
"""

from .client import LLMClient, chat, cost_meter
from .tools import run_tool_loop

__all__ = ["LLMClient", "chat", "cost_meter", "run_tool_loop"]
