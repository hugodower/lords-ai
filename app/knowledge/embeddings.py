from __future__ import annotations

from app.utils.logger import get_logger

log = get_logger("embeddings")


# ChromaDB uses its own default embedding function (all-MiniLM-L6-v2)
# We rely on that for Phase 1 — no need for external embedding API calls.


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap

    log.info("Chunked text into %d pieces (size=%d, overlap=%d)", len(chunks), chunk_size, overlap)
    return chunks
