"""Ingest the knowledge base into chunks.

Pipeline: load markdown docs -> chunk (sliding window with overlap). `build_corpus()` is
what the in-memory retrieval path searches over.

`ingest()` is the Qdrant-only step: when a real cluster is configured it embeds every
chunk once and upserts them into the collection (creating it if missing). On the default
in-memory path it is a no-op — the corpus is built at query time instead.

Heavy imports (embeddings, qdrant-client) are deferred into the functions that need them,
so importing this module is free and works without a live cluster.
"""

from __future__ import annotations

from project.config import KB_DIR, QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL, ROOT, USE_QDRANT
from project.schemas import Chunk


def load_docs() -> dict[str, str]:
    """Load every markdown doc in the KB, keyed by repo-relative path (for citations)."""
    docs: dict[str, str] = {}
    for path in sorted(KB_DIR.rglob("*.md")):
        docs[str(path.relative_to(ROOT))] = path.read_text()
    return docs


def chunk_text(text: str, source: str, size: int = 512, overlap: int = 64) -> list[Chunk]:
    """Split `text` into overlapping windows, carrying `source` for citations.

    `size`/`overlap` are in characters here for simplicity; in production prefer
    token-aware chunking (e.g. tiktoken) so chunks fit the model window predictably.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    text = text.strip()
    if len(text) <= size:
        return [Chunk(text=text, source=source)] if text else []

    chunks: list[Chunk] = []
    step = size - overlap
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(Chunk(text=piece, source=source))
        if start + size >= len(text):
            break
    return chunks


def build_corpus(size: int = 512, overlap: int = 64) -> list[Chunk]:
    """Chunk every KB doc into one flat list of Chunks."""
    chunks: list[Chunk] = []
    for source, text in load_docs().items():
        chunks.extend(chunk_text(text, source, size=size, overlap=overlap))
    return chunks


def ingest() -> int:
    """Ensure the Qdrant collection exists and holds the current corpus.

    When `USE_QDRANT`, embed every chunk once and upsert into `QDRANT_COLLECTION`
    (created if missing). Otherwise no-op — the in-memory path builds at query time.

    Returns the number of chunks upserted (0 on the in-memory path).
    """
    if not USE_QDRANT:
        return 0

    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from project.retrieval.embeddings import embed

    chunks = build_corpus()
    if not chunks:
        return 0

    vectors = embed([c.text for c in chunks])
    dim = len(vectors[0])

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None)
    if not client.collection_exists(QDRANT_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )

    points = [
        PointStruct(
            id=i,
            vector=[float(x) for x in vec],
            payload={"text": c.text, "source": c.source},
        )
        for i, (c, vec) in enumerate(zip(chunks, vectors))
    ]
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)
    return len(points)


if __name__ == "__main__":
    docs = load_docs()
    corpus = build_corpus()
    print(f"Produced {len(corpus)} chunks from {len(docs)} KB docs.")
    if USE_QDRANT:
        n = ingest()
        print(f"Upserted {n} chunks into Qdrant collection '{QDRANT_COLLECTION}'.")
    else:
        print("USE_QDRANT is off — corpus is built in-memory at query time (no upsert).")
