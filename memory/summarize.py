"""Context summarization — keep the window (and cost) bounded.

History grows every turn. When it crosses a token budget, replace the OLDEST turns with one
compact summary message and keep the last few raw. Trade-off: summarize the tail only, keep
recent turns verbatim, or you lose detail the agent still needs (e.g. the exact KPI the
analyst is drilling into).

Loom & Co. example: an analyst drills from *"net revenue by category last quarter"* into
*"now just Outerwear"* into *"and only the West region"*. After a dozen turns the early SQL
and figures can be compressed to one summary, while the last few turns stay verbatim so the
next follow-up still resolves "that" and "those numbers" correctly.

Used as a node (or pre-model hook) in the graph — but this module never imports the graph.
"""

from __future__ import annotations

from project.config import SPECIALIST_MODEL
from shared.llm import chat

Message = dict[str, str]

SUMMARY_PROMPT = (
    "Summarize the earlier part of this Loom & Co. BI-analysis conversation into a compact "
    "running summary. Preserve metrics, figures, the regions/categories in scope, decisions, "
    "and the analyst's intent. Be terse."
)


def estimate_tokens(text: str | list[Message]) -> int:
    """Rough token estimate (~4 chars/token). Good enough to trigger summarization.

    Accepts either a string or a list of message dicts. For accurate counts use a tokenizer
    (e.g. the provider's count_tokens endpoint); a char-based heuristic is fine purely to
    decide *when* to compress.
    """
    if isinstance(text, str):
        return len(text) // 4
    return sum(len(m["content"]) for m in text) // 4


def maybe_summarize(
    messages: list[Message],
    token_budget: int = 3000,
    keep_last: int = 6,
) -> list[Message]:
    """If over budget, compress all but the last `keep_last` turns into one summary message.

    Returns the (possibly) shortened message list. A no-op when under budget or when there's
    nothing before the kept tail to compress. Compression uses the cheap SPECIALIST_MODEL.
    """
    if estimate_tokens(messages) <= token_budget:
        return messages

    head, tail = messages[:-keep_last], messages[-keep_last:]
    if not head:
        return messages

    transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in head)
    summary = chat(f"{SUMMARY_PROMPT}\n\n{transcript}", model=SPECIALIST_MODEL)
    return [{"role": "system", "content": f"Earlier context summary:\n{summary}"}, *tail]


def summarize_turns(turns: list[tuple[str, str]], prior_summary: str = "") -> str:
    """Fold (question, answer) turns — plus any prior summary — into ONE rolling summary.

    This is the turn-shaped entry point used by `history.py`: when a thread's raw turns grow
    past its budget, the oldest turns are compressed into the running summary (keeping the last
    few raw), so long conversations stay bounded WITHOUT dropping earlier context outright.
    Rolling = we fold the previous summary in, so the result covers everything summarized so far.
    """
    transcript = "\n".join(f'Analyst asked: "{q}"\nYou answered: "{a}"' for q, a in turns)
    prior = f"Summary so far:\n{prior_summary}\n\n" if prior_summary else ""
    return chat(f"{prior}{SUMMARY_PROMPT}\n\n{transcript}", model=SPECIALIST_MODEL)


if __name__ == "__main__":
    demo = [{"role": "user", "content": "category margin chatter " * 200} for _ in range(8)]
    print(f"before: {len(demo)} msgs / ~{estimate_tokens(demo)} tok")
    after = maybe_summarize(demo)
    print(f"after:  {len(after)} msgs / ~{estimate_tokens(after)} tok")
