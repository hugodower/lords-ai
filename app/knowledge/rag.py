from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import settings
from app.knowledge.embeddings import chunk_text
from app.utils.logger import get_logger

log = get_logger("rag")

_client: Any = None


def get_chroma():
    """Lazily create ChromaDB HttpClient. May raise if server is unreachable."""
    global _client
    if _client is None:
        import chromadb

        url = settings.chroma_url.rstrip("/")
        host = url.replace("http://", "").replace("https://", "")
        port = 8000
        if ":" in host:
            host, port_str = host.rsplit(":", 1)
            port = int(port_str)
        _client = chromadb.HttpClient(host=host, port=port)
        log.info("ChromaDB client initialized (%s:%d)", host, port)
    return _client


def ping_chroma() -> bool:
    try:
        client = get_chroma()
        client.heartbeat()
        return True
    except Exception:
        return False


def _collection_name(org_id: str) -> str:
    safe = org_id.replace("-", "_")
    return f"org_{safe}"


async def index_document(
    org_id: str, document_name: str, content: str
) -> int:
    """Index a document into ChromaDB for RAG retrieval."""
    try:
        client = get_chroma()
    except Exception as e:
        log.warning("ChromaDB unavailable, skipping index: %s", e)
        return 0

    collection = client.get_or_create_collection(name=_collection_name(org_id))

    chunks = chunk_text(content)
    if not chunks:
        return 0

    ids = [f"{document_name}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": document_name, "org_id": org_id, "chunk": i} for i in range(len(chunks))]

    collection.upsert(
        ids=ids,
        documents=chunks,
        metadatas=metadatas,
    )

    log.info("Indexed %d chunks from '%s' for org %s", len(chunks), document_name, org_id)
    return len(chunks)


async def search_knowledge(
    org_id: str, query: str, limit: int = 5
) -> list[dict]:
    """Search the knowledge base for relevant content."""
    try:
        client = get_chroma()
        collection_name = _collection_name(org_id)

        try:
            collection = client.get_collection(name=collection_name)
        except Exception:
            return []

        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[query],
            n_results=min(limit, collection.count()),
        )

        items = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                score = 1.0 - (results["distances"][0][i] if results.get("distances") else 0)
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                items.append({"text": doc, "score": score, "metadata": metadata})

        log.info("RAG search for org %s: %d results", org_id, len(items))
        return items

    except Exception as e:
        log.warning("RAG search failed: %s", e)
        return []


async def save_conversation(
    org_id: str,
    conversation_id: str,
    history: list[dict],
    contact_name: str = "",
    outcome: str = "handoff",
) -> int:
    """Save a completed conversation to ChromaDB as training data for RAG.

    Each conversation is stored as a single document with all messages,
    so future RAG searches can find similar past interactions.
    Returns the number of chunks indexed (0 if failed).
    """
    if not history or len(history) < 2:
        log.info("Skipping RAG save — conversation too short (%d msgs)", len(history))
        return 0

    try:
        client = get_chroma()
    except Exception as e:
        log.warning("ChromaDB unavailable, skipping conversation save: %s", e)
        return 0

    # Build a readable conversation text
    lines = []
    for msg in history:
        role = "Lead" if msg.get("role") == "user" else "Atendente"
        lines.append(f"{role}: {msg.get('content', '')}")

    conversation_text = "\n".join(lines)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    doc_name = f"conv_{conversation_id}_{now}"

    collection = client.get_or_create_collection(name=_collection_name(org_id))

    chunks = chunk_text(conversation_text)
    if not chunks:
        return 0

    ids = [f"{doc_name}_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "source": "conversation",
            "org_id": org_id,
            "conversation_id": conversation_id,
            "contact_name": contact_name or "unknown",
            "outcome": outcome,
            "date": now,
            "chunk": i,
        }
        for i in range(len(chunks))
    ]

    collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)

    log.info(
        "Saved conversation to RAG: conv=%s org=%s chunks=%d outcome=%s",
        conversation_id, org_id, len(chunks), outcome,
    )
    return len(chunks)


async def delete_collection(org_id: str) -> None:
    """Delete all knowledge for an org."""
    try:
        client = get_chroma()
        client.delete_collection(name=_collection_name(org_id))
        log.info("Deleted knowledge collection for org %s", org_id)
    except Exception:
        pass
