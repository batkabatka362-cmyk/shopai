"""Global Brain — memory writer.

Writes scored knowledge items to both the vector store and memory store.
Coordinates dual-write to ensure both stores stay in sync.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

from typing import Any

from .vector_store import VectorStore
from .memory_store import MemoryStore


def write_to_stores(
    scored_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write scored knowledge items to vector store and memory store.

    Each item is added to the vector store (for similarity search)
    and the memory store (for structured retrieval).

    Args:
        scored_items: List of scored StructuredKnowledge dicts.

    Returns:
        Structured dict with write status and counts.
    """
    try:
        if not scored_items:
            return {
                "status": "success",
                "vector_written": 0,
                "memory_written": 0,
                "errors": [],
                "error": None,
            }

        vector_store = VectorStore(persist=True)
        memory_store = MemoryStore()

        vector_written = 0
        memory_written = 0
        errors: list[str] = []

        for item in scored_items:
            entry_id = item.get("knowledge_id", "")
            content = item.get("content", "")
            if not entry_id or not content:
                continue

            # Build metadata for vector store
            metadata = {
                "knowledge_type": item.get("knowledge_type", ""),
                "category": item.get("category", ""),
                "subcategory": item.get("subcategory", ""),
                "source_engine": item.get("source_engine", ""),
                "confidence": item.get("confidence", 0.0),
                "score": item.get("score", 0.0),
                "tags": item.get("tags", []),
            }
            timestamp = item.get("timestamp", "")

            # Write to vector store
            try:
                vector_store.add(
                    entry_id=entry_id,
                    content=content,
                    metadata=metadata,
                    timestamp=timestamp,
                )
                vector_written += 1
            except Exception as exc:
                errors.append(f"Vector write failed for {entry_id}: {exc}")

            # Write to memory store
            try:
                result = memory_store.write(
                    entry_id=entry_id,
                    knowledge=item,
                    score=item.get("score", 0.0),
                )
                if result.get("status") == "success":
                    memory_written += 1
                else:
                    errors.append(result.get("note", f"Memory write failed for {entry_id}"))
            except Exception as exc:
                errors.append(f"Memory write failed for {entry_id}: {exc}")

        return {
            "status": "success",
            "vector_written": vector_written,
            "memory_written": memory_written,
            "errors": errors,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "vector_written": 0,
            "memory_written": 0,
            "errors": [],
            "error": f"Store write failed: {exc}",
        }
