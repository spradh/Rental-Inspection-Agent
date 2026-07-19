"""Embedding + reranking models for KB retrieval.

Two models, both lazy and cached so importing this module is free (no downloads, no
network) — they load on first use:

  - a bi-encoder (`EMBED_MODEL`) for fast first-pass cosine search, and
  - a cross-encoder (`RERANK_MODEL`) for a precise second-pass rerank.

sentence-transformers is imported inside the loaders so this module imports without it
present and without touching the network.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from project.config import EMBED_MODEL, RERANK_MODEL
from project.schemas import Chunk


@lru_cache(maxsize=1)
def _bi_encoder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANK_MODEL)


def embed(texts: list[str]) -> np.ndarray:
    """Return one L2-normalized embedding per text (so dot product == cosine)."""
    return _bi_encoder().encode(texts, normalize_embeddings=True)


def rerank(query: str, candidates: list[Chunk], top_n: int = 5) -> list[Chunk]:
    """Precise second pass: the cross-encoder scores each (query, chunk) pair directly,
    then we keep the top_n. Returns new Chunks carrying the rerank score."""
    if not candidates:
        return []
    pairs = [(query, c.text) for c in candidates]
    scores = _cross_encoder().predict(pairs)
    reranked = sorted(
        (Chunk(text=c.text, source=c.source, score=float(s)) for c, s in zip(candidates, scores)),
        key=lambda c: c.score,
        reverse=True,
    )
    return reranked[:top_n]
