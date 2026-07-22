"""Thread persistence — give the BI Analyst Agent a memory.

A LangGraph *checkpointer* snapshots graph state after every step. The graph is compiled
with one and passed a `thread_id` on invoke; it then resumes that thread's last state. Same
graph code, swappable backend: InMemorySaver (dev) -> RedisSaver (prod).

This module owns ONLY the checkpointer factory — it does not import or build the agent graph.
The graph imports `make_checkpointer` from here, never the other way around. LangGraph bits
are imported lazily inside the function so this module imports fine without a live Redis (or
even without the redis package installed) when running in-memory.
"""

from __future__ import annotations

from project.config import REDIS_URL, USE_REDIS


def make_checkpointer():
    """Return a checkpointer based on config.

    When `USE_REDIS` is set, build a RedisSaver from `langgraph-checkpoint-redis` against
    `REDIS_URL` and call `.setup()` to create the checkpoint indices. Otherwise return an
    InMemorySaver. The langgraph imports are lazy so importing this module never requires a
    running Redis.
    """
    if USE_REDIS:
        from langgraph.checkpoint.redis import RedisSaver

        # `.from_conn_string(...)` returns a context manager; entering it yields the saver.
        # We keep it open for the lifetime of the process (one long-lived worker).
        cm = RedisSaver.from_conn_string(REDIS_URL)
        saver = cm.__enter__()
        saver.setup()  # one-time: create the checkpoint indices in Redis
        return saver

    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


if __name__ == "__main__":
    cp = make_checkpointer()
    print(f"checkpointer = {type(cp).__name__}")
