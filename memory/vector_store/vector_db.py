"""Vector DB -- simple in-memory vector store with cosine similarity search."""
from __future__ import annotations

import math
from typing import Any


class VectorDB:
    """In-memory vector database supporting cosine-similarity search."""

    def __init__(self) -> None:
        # _collections maps collection_name -> {doc_id -> {"vector": [...], "metadata": {...}}}
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}

    # ---- Public API -------------------------------------------------------

    def add(
        self,
        collection: str,
        doc_id: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        """Add a document vector to a collection."""
        if collection not in self._collections:
            self._collections[collection] = {}
        self._collections[collection][doc_id] = {
            "vector": vector,
            "metadata": metadata or {},
        }

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Return the *top_k* most similar documents by cosine similarity.

        Each result dict has keys: doc_id, score, metadata.
        """
        col = self._collections.get(collection, {})
        scored: list[tuple[str, float, dict]] = []
        for doc_id, entry in col.items():
            sim = self._cosine_similarity(query_vector, entry["vector"])
            scored.append((doc_id, sim, entry["metadata"]))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[dict] = []
        for doc_id, score, meta in scored[:top_k]:
            results.append({
                "doc_id": doc_id,
                "score": score,
                "metadata": meta,
            })
        return results

    def delete(self, collection: str, doc_id: str) -> bool:
        """Delete a document from a collection. Returns True if it existed."""
        col = self._collections.get(collection, {})
        if doc_id not in col:
            return False
        del col[doc_id]
        # Clean up empty collections
        if not col:
            self._collections.pop(collection, None)
        return True

    def list_collections(self) -> list[str]:
        """Return sorted list of collection names."""
        return sorted(self._collections.keys())

    def get_collection_stats(self, collection: str) -> dict:
        """Return stats for a collection."""
        col = self._collections.get(collection, {})
        if not col:
            return {
                "collection": collection,
                "document_count": 0,
                "vector_dim": None,
            }
        sample_vec = next(iter(col.values()))["vector"]
        return {
            "collection": collection,
            "document_count": len(col),
            "vector_dim": len(sample_vec),
        }

    # ---- Private helpers --------------------------------------------------

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b):
            return 0.0

        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for a, b in zip(vec_a, vec_b):
            dot += a * b
            norm_a += a * a
            norm_b += b * b

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
