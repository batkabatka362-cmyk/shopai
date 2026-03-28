"""Embedding Manager — manages text embeddings."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger

logger = get_logger("memory.embeddings")


class EmbeddingManager:
    def embed(self, text: str) -> list[float]:
        logger.info("Embedding text (len=%d)", len(text))
        return [0.0] * 384  # Placeholder: actual embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]
