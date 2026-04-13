"""Global Brain — memory reader.

Reads from both vector store and memory store with filtering.
Provides a unified interface for retrieving stored knowledge.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import copy
from typing import Any

from .vector_store import VectorStore
from .memory_store import MemoryStore


def read_from_stores(
    query: str = "",
    category: str = "",
    source_engine: str = "",
    top_k: int = 10,
) -> dict[str, Any]:
    """Read knowledge from both stores.

    If a query is provided, uses vector similarity search.
    Otherwise, returns records filtered by category/source.

    Args:
        query: Search query for vector similarity (optional).
        category: Filter by knowledge category (optional).
        source_engine: Filter by source engine (optional).
        top_k: Maximum results to return.

    Returns:
        Structured dict with vector_results, memory_results, and combined.
    """
    try:
        vector_store = VectorStore(persist=True)
        memory_store = MemoryStore()

        vector_results: list[dict[str, Any]] = []
        memory_results: list[dict[str, Any]] = []

        # Vector search (if query provided)
        if query:
            vector_results = vector_store.search(query=query, top_k=top_k)

        # Memory store read (filtered)
        memory_results = memory_store.read_all(
            category=category,
            source_engine=source_engine,
            limit=top_k,
        )

        # Combine results, dedup by entry_id
        seen_ids: set[str] = set()
        combined: list[dict[str, Any]] = []

        # Vector results first (ranked by similarity)
        for vr in vector_results:
            eid = vr.get("entry_id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                combined.append({
                    "entry_id": eid,
                    "content": vr.get("content", ""),
                    "similarity": vr.get("similarity", 0.0),
                    "metadata": vr.get("metadata", {}),
                    "timestamp": vr.get("timestamp", ""),
                    "source": "vector",
                })

        # Memory results next (ranked by score)
        for mr in memory_results:
            eid = mr.get("entry_id", "")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                knowledge = mr.get("knowledge", {})
                combined.append({
                    "entry_id": eid,
                    "content": knowledge.get("content", ""),
                    "similarity": 0.0,
                    "metadata": {
                        "category": knowledge.get("category", ""),
                        "source_engine": knowledge.get("source_engine", ""),
                        "score": mr.get("score", 0.0),
                    },
                    "timestamp": knowledge.get("timestamp", ""),
                    "source": "memory",
                })

        return {
            "status": "success",
            "vector_results": vector_results,
            "memory_results": memory_results,
            "combined": combined[:top_k],
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "vector_results": [],
            "memory_results": [],
            "combined": [],
            "error": f"Store read failed: {exc}",
        }
