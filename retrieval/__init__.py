"""Retrieval package for the BI Analyst Agent.

Public API:
  - search_kb(query, top_n) -> list[Chunk]   the main entry point (Qdrant or in-memory)
  - build_corpus()          -> list[Chunk]   chunk every KB doc
  - ingest()                -> int           upsert the corpus to Qdrant (no-op in-memory)
  - Chunk                                     the shared retrieval contract
"""

from __future__ import annotations

from project.schemas import Chunk

from project.retrieval.ingest import build_corpus, ingest
from project.retrieval.search import search_kb

__all__ = ["search_kb", "build_corpus", "ingest", "Chunk"]
