"""Embedding Manager -- deterministic text-to-vector embeddings with VectorDB integration."""
from __future__ import annotations

import hashlib
import math
import struct
import uuid
from typing import Any

from memory.vector_store.vector_db import VectorDB


class EmbeddingManager:
    """Manages text embeddings and integrates with VectorDB for storage and search."""

    def __init__(self, vector_db: VectorDB | None = None) -> None:
        self._vector_db: VectorDB = vector_db or VectorDB()

    # ---- Public API -------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        """Produce a deterministic 128-dimensional embedding for *text*."""
        return self._simple_hash_embed(text, dim=128)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        return [self.embed_text(t) for t in texts]

    def store_embedding(
        self,
        text: str,
        collection: str,
        metadata: dict | None = None,
    ) -> str:
        """Embed *text* and store it in the VectorDB. Returns the doc_id."""
        vector = self.embed_text(text)
        doc_id = uuid.uuid4().hex[:16]
        meta = dict(metadata) if metadata else {}
        meta["text"] = text
        self._vector_db.add(collection, doc_id, vector, metadata=meta)
        return doc_id

    def search_similar(
        self,
        query_text: str,
        collection: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Embed *query_text* and search for similar documents in *collection*."""
        query_vector = self.embed_text(query_text)
        return self._vector_db.search(collection, query_vector, top_k=top_k)

    # ---- Private helpers --------------------------------------------------

    @staticmethod
    def _simple_hash_embed(text: str, dim: int = 128) -> list[float]:
        """Deterministic text -> vector using SHA-512 based hashing.

        Generates *dim* float components in [-1, 1] by hashing the text
        with different salts and normalizing to unit length.
        """
        components: list[float] = []
        # SHA-512 produces 64 bytes = 16 floats per hash.
        # We need ceil(dim / 16) hash rounds.
        rounds = math.ceil(dim / 16)
        for i in range(rounds):
            salted = f"{i}:{text}".encode("utf-8")
            digest = hashlib.sha512(salted).digest()
            # Unpack 64 bytes as 16 unsigned 32-bit ints
            values = struct.unpack("<16I", digest)
            for v in values:
                # Map to [-1, 1]
                components.append((v / 0xFFFFFFFF) * 2.0 - 1.0)
                if len(components) >= dim:
                    break
            if len(components) >= dim:
                break

        components = components[:dim]

        # Normalize to unit vector
        magnitude = math.sqrt(sum(c * c for c in components))
        if magnitude > 0:
            components = [c / magnitude for c in components]

        return components
