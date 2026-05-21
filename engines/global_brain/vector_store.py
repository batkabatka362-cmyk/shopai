"""Global Brain — vector store.

Simple vector store using TF-IDF-style vectors and cosine similarity.
No external dependencies. Stores vectors in memory with optional
JSON persistence.

Store, search, and retrieve operations.
No connections to other modules — called only from memory_writer/memory_reader.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


_STORE_PATH = os.path.join(os.path.dirname(__file__), ".vector_store.json")

# Stop words excluded from TF-IDF computation
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "nor", "not", "so", "yet", "both", "either", "neither", "each",
    "every", "all", "any", "few", "more", "most", "other", "some",
    "such", "no", "only", "own", "same", "than", "too", "very",
    "this", "that", "these", "those", "it", "its", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom",
})


class VectorStore:
    """In-memory vector store with TF-IDF vectorization and cosine search."""

    def __init__(self, persist: bool = True) -> None:
        self._entries: list[dict[str, Any]] = []
        self._vocabulary: dict[str, int] = {}  # term -> index
        self._doc_freq: dict[str, int] = {}    # term -> document count
        self._persist = persist
        self._load()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def add(self, entry_id: str, content: str, metadata: dict[str, Any] | None = None,
            timestamp: str = "") -> None:
        """Add a document to the store.

        Computes a TF-IDF vector for the content and stores it alongside
        metadata.
        """
        tokens = _tokenize(content)
        if not tokens:
            return

        # Update vocabulary and document frequency
        unique_tokens = set(tokens)
        for token in unique_tokens:
            if token not in self._vocabulary:
                self._vocabulary[token] = len(self._vocabulary)
            self._doc_freq[token] = self._doc_freq.get(token, 0) + 1

        # Compute TF vector (we store raw TF; IDF applied at search time)
        tf: dict[str, float] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0.0) + 1.0
        # Normalize TF by max frequency
        max_tf = max(tf.values()) if tf else 1.0
        for token in tf:
            tf[token] = 0.5 + 0.5 * (tf[token] / max_tf)

        self._entries.append({
            "entry_id": entry_id,
            "content": content,
            "tf": tf,
            "tokens": list(unique_tokens),
            "metadata": metadata or {},
            "timestamp": timestamp,
        })

        if self._persist:
            self._save()

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search the store using cosine similarity on TF-IDF vectors.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of dicts with entry_id, content, similarity, metadata.
        """
        if not self._entries:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        n_docs = len(self._entries)

        # Compute query TF-IDF vector
        query_tf: dict[str, float] = {}
        for token in query_tokens:
            query_tf[token] = query_tf.get(token, 0.0) + 1.0
        max_qtf = max(query_tf.values()) if query_tf else 1.0
        query_tfidf: dict[str, float] = {}
        for token, raw_tf in query_tf.items():
            tf = 0.5 + 0.5 * (raw_tf / max_qtf)
            df = self._doc_freq.get(token, 0)
            idf = math.log((n_docs + 1) / (df + 1)) + 1.0
            query_tfidf[token] = tf * idf

        # Compute cosine similarity with each document
        results: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries:
            doc_tfidf: dict[str, float] = {}
            for token, tf in entry["tf"].items():
                df = self._doc_freq.get(token, 0)
                idf = math.log((n_docs + 1) / (df + 1)) + 1.0
                doc_tfidf[token] = tf * idf

            similarity = _cosine_similarity(query_tfidf, doc_tfidf)
            if similarity > 0.0:
                results.append((similarity, entry))

        results.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "entry_id": entry["entry_id"],
                "content": entry["content"],
                "similarity": round(sim, 4),
                "metadata": entry.get("metadata", {}),
                "timestamp": entry.get("timestamp", ""),
            }
            for sim, entry in results[:top_k]
        ]

    def get_all(self) -> list[dict[str, Any]]:
        """Return all entries (without internal TF data)."""
        return [
            {
                "entry_id": e["entry_id"],
                "content": e["content"],
                "metadata": e.get("metadata", {}),
                "timestamp": e.get("timestamp", ""),
            }
            for e in self._entries
        ]

    def get_by_id(self, entry_id: str) -> dict[str, Any] | None:
        """Retrieve a single entry by ID."""
        for entry in self._entries:
            if entry["entry_id"] == entry_id:
                return {
                    "entry_id": entry["entry_id"],
                    "content": entry["content"],
                    "metadata": entry.get("metadata", {}),
                    "timestamp": entry.get("timestamp", ""),
                }
        return None

    def count(self) -> int:
        """Return the number of entries."""
        return len(self._entries)

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def _save(self) -> None:
        """Persist store to disk."""
        try:
            data = {
                "entries": self._entries,
                "vocabulary": self._vocabulary,
                "doc_freq": self._doc_freq,
            }
            with open(_STORE_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
        except (OSError, TypeError, ValueError) as exc:
            # Silent loss of the vector store means search calls
            # return cold-start results next session and the
            # operator never knows the persistence step failed.
            # Same shape as the profit_tracker / global_brain
            # memory fixes.
            logger.warning(
                "VectorStore._save failed (%s): %s",
                _STORE_PATH, exc,
            )

    def _load(self) -> None:
        """Load store from disk if available."""
        if not os.path.isfile(_STORE_PATH):
            return
        try:
            with open(_STORE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._entries = data.get("entries", [])
                self._vocabulary = data.get("vocabulary", {})
                self._doc_freq = data.get("doc_freq", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "VectorStore._load failed (%s), starting "
                "with empty store: %s", _STORE_PATH, exc,
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercased words, removing stop words."""
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse TF-IDF vectors."""
    # Dot product
    dot = 0.0
    for term, val_a in vec_a.items():
        if term in vec_b:
            dot += val_a * vec_b[term]

    if dot == 0.0:
        return 0.0

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    return dot / (mag_a * mag_b)
