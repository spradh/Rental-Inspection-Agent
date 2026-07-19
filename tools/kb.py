"""Knowledge-base tools — semantic search + canonical metric lookup.

Two capabilities the agent uses to *ground* its answers before writing SQL:
  - `search_kb`   — semantic retrieval over the markdown KB (data dictionary, metric
                    definitions, glossary, policies), formatted with [source] citations.
  - `lookup_metric` — pull the canonical definition of a named KPI straight from
                    `metric-definitions.md`, so the agent uses the house definition
                    rather than improvising.

Both return a STRING observation and never raise.

Demo:
    python -m project.tools.kb
"""

from __future__ import annotations

from project.config import KB_DIR
from project.retrieval import search_kb as _retrieve

METRIC_FILE = KB_DIR / "metric-definitions.md"


def search_kb(query: str, top_n: int = 5) -> str:
    """Retrieve the most relevant KB passages and format them with citations."""
    if not isinstance(query, str) or not query.strip():
        return "search_kb: empty query."
    try:
        chunks = _retrieve(query, top_n=top_n)
    except Exception as e:  # noqa: BLE001
        return f"search_kb error: {e}"
    if not chunks:
        return f"No KB passages found for: {query!r}"
    lines = []
    for i, c in enumerate(chunks, 1):
        text = " ".join(c.text.split())          # collapse whitespace for compactness
        lines.append(f"[{i}] {text}\n    — source: {c.source} (score {c.score:.3f})")
    return "\n\n".join(lines)


def _split_metric_blocks(md: str) -> list[tuple[str, str]]:
    """Split metric-definitions.md into (heading, body) bullet blocks.

    Each canonical metric is a top-level bullet ("- **Name** = …"), sometimes with
    indented sub-bullets. We keep the whole bullet + its children together.
    """
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    for raw in md.splitlines():
        is_top_bullet = raw.startswith("- ")
        if is_top_bullet and current:
            blocks.append((current[0], "\n".join(current)))
            current = []
        if is_top_bullet:
            current = [raw]
        elif current and (raw.startswith("  ") or raw.startswith("\t") or not raw.strip()):
            current.append(raw)
        elif current:
            # a non-indented, non-bullet line (e.g. a new section header) ends the block
            blocks.append((current[0], "\n".join(current)))
            current = []
    if current:
        blocks.append((current[0], "\n".join(current)))
    return blocks


def lookup_metric(name: str) -> str:
    """Grep the canonical definition of a metric from metric-definitions.md."""
    if not isinstance(name, str) or not name.strip():
        return "lookup_metric: empty metric name."
    try:
        md = METRIC_FILE.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"lookup_metric error: cannot read {METRIC_FILE}: {e}"

    needle = name.strip().lower()
    blocks = _split_metric_blocks(md)
    hits = [body for heading, body in blocks if needle in heading.lower()]
    if not hits:
        # fall back to a looser match anywhere in the bullet body
        hits = [body for _, body in blocks if needle in body.lower()]
    if not hits:
        known = ", ".join(
            h.split("**")[1] for h, _ in blocks if "**" in h
        ) or "(none parsed)"
        return (
            f"No canonical definition found for {name!r} in {METRIC_FILE.name}.\n"
            f"Known metrics: {known}"
        )
    return (
        f"Canonical definition(s) for {name!r} (source: {METRIC_FILE.name}):\n\n"
        + "\n\n".join(hits)
    )


if __name__ == "__main__":
    print("== search_kb ==")
    print(search_kb("how is net revenue defined", top_n=3))
    print("\n== lookup_metric ==")
    print(lookup_metric("Net revenue"))
