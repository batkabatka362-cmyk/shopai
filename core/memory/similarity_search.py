"""Similarity Search — find memories by feature similarity, not just category."""
from __future__ import annotations
import math
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("memory.similarity")


class SimilaritySearch:
    """Find similar memories using feature-based cosine similarity."""

    def search(self, query_features: dict, category: str = "",
               limit: int = 10, min_similarity: float = 0.3) -> list[dict]:
        """Find memories similar to query features."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return []

        # Get candidate memories
        if category:
            candidates = mi.retrieve(category, limit=100)
        else:
            candidates = mi.retrieve("", limit=100)

        # Score by similarity
        scored = []
        for m in candidates:
            features = m.get("features", {})
            if not isinstance(features, dict):
                continue
            sim = self._cosine(query_features, features)
            if sim >= min_similarity:
                scored.append({**m, "_similarity": round(sim, 3)})

        scored.sort(key=lambda x: -x.get("_similarity", 0))
        return scored[:limit]

    def find_similar_decisions(self, action: str, features: dict,
                               limit: int = 5) -> list[dict]:
        """Find past decisions similar to a proposed action."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
        except Exception:
            return []

        conn = mi._conn()
        rows = conn.execute(
            "SELECT * FROM memories WHERE action = ? AND level = 0 ORDER BY score DESC LIMIT 50",
            (action,),
        ).fetchall()

        scored = []
        for r in rows:
            m = mi._row_to_dict(r)
            f = m.get("features", {})
            if isinstance(f, dict):
                sim = self._cosine(features, f)
                if sim > 0.2:
                    scored.append({
                        "id": m.get("id"),
                        "action": m.get("action"),
                        "score": m.get("score", 0),
                        "similarity": round(sim, 3),
                    })

        scored.sort(key=lambda x: -x["similarity"])
        return scored[:limit]

    @staticmethod
    def _cosine(a: dict, b: dict) -> float:
        all_keys = set(list(a.keys()) + list(b.keys()))
        if not all_keys:
            return 0.0
        dot = norm_a = norm_b = 0.0
        for k in all_keys:
            va = _to_num(a.get(k))
            vb = _to_num(b.get(k))
            dot += va * vb
            norm_a += va * va
            norm_b += vb * vb
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _to_num(val) -> float:
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


_instance = None
def get_similarity_search():
    global _instance
    if _instance is None:
        _instance = SimilaritySearch()
    return _instance
