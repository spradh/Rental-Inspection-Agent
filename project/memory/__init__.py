"""Memory package for the BI Analyst Agent.

Three kinds of memory, each decoupled from the agent graph (the graph imports this package,
never the reverse):

  - Thread persistence (short-term, per thread_id) — `make_checkpointer`
  - Conversation history (per thread_id)            — `append_turn`, `render_context`
  - Personalization     (long-term, per user_id)   — `UserProfile`, `load_profile`,
                                                      `save_profile`, `apply_profile`,
                                                      `learn_from_query`
  - Context summarization (window control)          — `maybe_summarize`
"""

from __future__ import annotations

from project.memory.checkpointer import make_checkpointer
from project.memory.history import append_turn, recent_turns, render_context
from project.memory.history import clear as clear_history
from project.memory.personalization import (
    UserProfile,
    apply_profile,
    learn_from_query,
    load_profile,
    save_profile,
)
from project.memory.summarize import maybe_summarize

__all__ = [
    "make_checkpointer",
    "append_turn",
    "recent_turns",
    "render_context",
    "clear_history",
    "UserProfile",
    "load_profile",
    "save_profile",
    "apply_profile",
    "learn_from_query",
    "maybe_summarize",
]
