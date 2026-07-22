"""Knowledge-base search: one signature, two backends.

`search_kb(query, top_n)` returns the top_n most relevant Chunks. Both backends are a
two-stage pipeline — a fast bi-encoder first pass to top-k candidates, then a precise
cross-encoder rerank to top_n:

  - USE_QDRANT: embed the query, fetch top-k from the Qdrant collection, then rerank.
  - else (default): build the corpus once (cached module-level), bi-encoder cosine
    search to top-k, then rerank.

Heavy imports are deferred so this module imports without models or a live cluster.
"""

from __future__ import annotations

from project.config import QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL, USE_QDRANT
from project.schemas import Chunk

# First-pass candidate pool size handed to the reranker.
_TOP_K = 50

# In-memory corpus, built once on first query and reused thereafter.
_CORPUS: list[Chunk] | None = None


def _corpus() -> list[Chunk]:
    global _CORPUS
    if _CORPUS is None:
        from project.retrieval.ingest import build_corpus

        _CORPUS = build_corpus()
    return _CORPUS


def _search_in_memory(query: str, top_n: int) -> list[Chunk]:
    from project.retrieval.embeddings import embed, rerank

    chunks = _corpus()
    if not chunks:
        return []

    q = embed([query])[0]
    doc_vecs = embed([c.text for c in chunks])
    scores = doc_vecs @ q
    ranked = sorted(
        (Chunk(text=c.text, source=c.source, score=float(s)) for c, s in zip(chunks, scores)),
        key=lambda c: c.score,
        reverse=True,
    )
    return rerank(query, ranked[:_TOP_K], top_n=top_n)


def _search_qdrant(query: str, top_n: int) -> list[Chunk]:
    from qdrant_client import QdrantClient

    from project.retrieval.embeddings import embed, rerank

    q = embed([query])[0]
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    hits = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=[float(x) for x in q],
        limit=_TOP_K,
        with_payload=True,
    ).points

    candidates = [
        Chunk(
            text=h.payload.get("text", ""),
            source=h.payload.get("source", ""),
            score=float(h.score),
        )
        for h in hits
    ]
    return rerank(query, candidates, top_n=top_n)


def search_kb(query: str, top_n: int = 5) -> list[Chunk]:
    """Return the top_n most relevant KB chunks for `query` (Qdrant or in-memory)."""
    if USE_QDRANT:
        return _search_qdrant(query, top_n)
    return _search_in_memory(query, top_n)


if __name__ == "__main__":
    for c in search_kb("how is gross margin computed?", top_n=3):
        print(f"{c.score:.3f}  [{c.source}]  {c.text[:80]}")
