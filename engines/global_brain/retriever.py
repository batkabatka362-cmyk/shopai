"""Global Brain — retriever.

Retrieves relevant knowledge given a query by combining three signals:
vector similarity (TF-IDF cosine), keyword matching, and recency.
Produces a ranked list of RetrievalResult items.

No connections to other modules — called only from flow.py.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .vector_store import VectorStore
from .memory_store import MemoryStore


# Weights for combining retrieval signals
_SIGNAL_WEIGHTS = {
    "vector": 0.45,
    "keyword": 0.30,
    "recency": 0.25,
}


def retrieve_knowledge(
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """Retrieve relevant knowledge combining multiple signals.

    Signals:
        1. Vector similarity: TF-IDF cosine similarity from vector store.
        2. Keyword matching: direct keyword overlap between query and content.
        3. Recency: time-based decay favoring recent knowledge.

    Args:
        query: The search query string.
        max_results: Maximum number of results.

    Returns:
        Structured dict with status and retrieval_results list.
    """
    try:
        if not query or not query.strip():
            return {
                "status": "success",
                "retrieval_results": [],
                "error": None,
            }

        vector_store = VectorStore(persist=True)
        memory_store = MemoryStore()

        # ---- Signal 1: Vector similarity ----
        vector_results = vector_store.search(query=query, top_k=max_results * 3)
        vector_scores: dict[str, float] = {}
        vector_data: dict[str, dict[str, Any]] = {}
        for vr in vector_results:
            eid = vr.get("entry_id", "")
            if eid:
                vector_scores[eid] = vr.get("similarity", 0.0)
                vector_data[eid] = vr

        # ---- Signal 2: Keyword matching ----
        query_tokens = set(_tokenize(query))
        all_records = memory_store.read_all(limit=200)
        keyword_scores: dict[str, float] = {}
        memory_data: dict[str, dict[str, Any]] = {}

        for record in all_records:
            eid = record.get("entry_id", "")
            if not eid:
                continue
            knowledge = record.get("knowledge", {})
            content = knowledge.get("content", "")
            tags = set(knowledge.get("tags", []))

            content_tokens = set(_tokenize(content))
            if not content_tokens and not tags:
                continue

            # Token overlap
            overlap = query_tokens & content_tokens
            if content_tokens:
                token_score = len(overlap) / len(query_tokens) if query_tokens else 0.0
            else:
                token_score = 0.0

            # Tag overlap (query words matching tags)
            tag_overlap = query_tokens & {t.lower() for t in tags}
            tag_score = len(tag_overlap) / len(query_tokens) if query_tokens else 0.0

            keyword_scores[eid] = 0.7 * token_score + 0.3 * tag_score
            memory_data[eid] = record

        # ---- Signal 3: Recency ----
        now = time.time()
        recency_scores: dict[str, float] = {}
        all_ids = set(vector_scores.keys()) | set(keyword_scores.keys())

        for eid in all_ids:
            ts_str = ""
            if eid in vector_data:
                ts_str = vector_data[eid].get("timestamp", "")
            elif eid in memory_data:
                k = memory_data[eid].get("knowledge", {})
                ts_str = k.get("timestamp", "")

            recency_scores[eid] = _compute_recency_score(ts_str, now)

        # ---- Combine signals ----
        combined: dict[str, float] = {}
        for eid in all_ids:
            vs = vector_scores.get(eid, 0.0)
            ks = keyword_scores.get(eid, 0.0)
            rs = recency_scores.get(eid, 0.5)
            combined[eid] = (
                _SIGNAL_WEIGHTS["vector"] * vs
                + _SIGNAL_WEIGHTS["keyword"] * ks
                + _SIGNAL_WEIGHTS["recency"] * rs
            )

        # ---- Rank and build results ----
        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
        results: list[dict[str, Any]] = []

        for eid, score in ranked[:max_results]:
            if score <= 0.0:
                continue

            # Get content and metadata from whichever source has it
            content = ""
            category = ""
            source_engine = ""
            knowledge_type = ""
            timestamp = ""

            if eid in memory_data:
                k = memory_data[eid].get("knowledge", {})
                content = k.get("content", "")
                category = k.get("category", "")
                source_engine = k.get("source_engine", "")
                knowledge_type = k.get("knowledge_type", "")
                timestamp = k.get("timestamp", "")
            elif eid in vector_data:
                vd = vector_data[eid]
                content = vd.get("content", "")
                meta = vd.get("metadata", {})
                category = meta.get("category", "")
                source_engine = meta.get("source_engine", "")
                knowledge_type = meta.get("knowledge_type", "")
                timestamp = vd.get("timestamp", "")

            results.append({
                "entry_id": eid,
                "content": content,
                "category": category,
                "relevance_score": round(score, 4),
                "source_engine": source_engine,
                "timestamp": timestamp,
                "knowledge_type": knowledge_type,
            })

        return {
            "status": "success",
            "retrieval_results": results,
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "error",
            "retrieval_results": [],
            "error": f"Retrieval failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "and", "or", "but",
    "not", "this", "that", "it", "as", "so",
})


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercased words, removing stop words."""
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _compute_recency_score(timestamp_str: str, now: float) -> float:
    """Compute a recency score from a timestamp string."""
    if not timestamp_str:
        return 0.5

    try:
        ts = time.mktime(time.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%SZ"))
        age_hours = max((now - ts) / 3600.0, 0.0)
    except (ValueError, OverflowError):
        return 0.5

    # Exponential decay: half-life of 168 hours (1 week)
    half_life = 168.0
    decay = 0.5 ** (age_hours / half_life)
    return max(decay, 0.05)
