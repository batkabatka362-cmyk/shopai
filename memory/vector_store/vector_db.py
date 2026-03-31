"""Vector DB -- vector store with cosine similarity search + disk persistence.

Supports:
  - Collections of vectors with metadata
  - Cosine similarity search (top-k)
  - Save/load to JSON (survives restarts)
  - Auto-save after mutations when path configured
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

from utils.logger import get_logger

logger = get_logger("memory.vector_db")


class VectorDB:
    """Vector database with cosine-similarity search and optional disk persistence."""

    def __init__(self, persist_path: str | None = None) -> None:
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}
        self._persist_path = persist_path
        self._dirty = False
        if persist_path:
            self._load_from_disk()

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
        self._dirty = True
        self._auto_save()

    def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Return the *top_k* most similar documents by cosine similarity."""
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
                "score": round(score, 4),
                "metadata": meta,
            })
        return results

    def delete(self, collection: str, doc_id: str) -> bool:
        """Delete a document from a collection."""
        col = self._collections.get(collection, {})
        if doc_id not in col:
            return False
        del col[doc_id]
        if not col:
            self._collections.pop(collection, None)
        self._dirty = True
        self._auto_save()
        return True

    def list_collections(self) -> list[str]:
        return sorted(self._collections.keys())

    def get_collection_stats(self, collection: str) -> dict:
        col = self._collections.get(collection, {})
        if not col:
            return {"collection": collection, "document_count": 0, "vector_dim": None}
        sample_vec = next(iter(col.values()))["vector"]
        return {
            "collection": collection,
            "document_count": len(col),
            "vector_dim": len(sample_vec),
        }

    def total_documents(self) -> int:
        """Total documents across all collections."""
        return sum(len(col) for col in self._collections.values())

    # ---- Persistence -------------------------------------------------------

    def save(self, path: str | None = None) -> bool:
        """Save all collections to JSON file."""
        target = path or self._persist_path
        if not target:
            return False
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._collections, f)
            os.replace(tmp, target)
            self._dirty = False
            logger.info("VectorDB saved: %d documents to %s", self.total_documents(), target)
            return True
        except Exception as exc:
            logger.error("VectorDB save failed: %s", exc)
            return False

    def load(self, path: str | None = None) -> bool:
        """Load collections from JSON file."""
        target = path or self._persist_path
        if not target or not os.path.exists(target):
            return False
        try:
            with open(target) as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._collections = data
                self._dirty = False
                logger.info("VectorDB loaded: %d documents from %s", self.total_documents(), target)
                return True
        except Exception as exc:
            logger.error("VectorDB load failed: %s", exc)
        return False

    # ---- Private helpers --------------------------------------------------

    def _load_from_disk(self) -> None:
        """Load from persist_path on init."""
        if self._persist_path and os.path.exists(self._persist_path):
            self.load()

    def _auto_save(self) -> None:
        """Auto-save if persist_path configured and dirty."""
        if self._persist_path and self._dirty:
            # Batch saves: only save every N mutations
            total = self.total_documents()
            if total % 10 == 0 or total <= 5:
                self.save()

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
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
