"""Smoke test for the shared LLM client.

Run:  python -m shared.llm
"""

from .client import DEFAULT_MODEL, chat

if __name__ == "__main__":
    print(f"Default model: {DEFAULT_MODEL}")
    print(chat("Reply with exactly: 'LLM client is wired up.'"))
