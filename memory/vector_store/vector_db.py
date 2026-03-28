"""Vector DB — vector similarity search store."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("memory.vector_db")


class VectorDB:
    def __init__(self) -> None:
        self._vectors: list[dict[str, Any]] = []

    def add(self, id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        self._vectors.append({"id": id, "vector": vector, "metadata": metadata or {}})

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        logger.info("Searching %d vectors (top_k=%d)", len(self._vectors), top_k)
        return self._vectors[:top_k]  # Placeholder: actual similarity search

    def size(self) -> int:
        return len(self._vectors)
