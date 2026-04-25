"""Legacy memory package — still exports the 4 storage
primitives (ShortTermCache, PersistentStore, VectorDB,
EmbeddingManager) for existing import sites. New code
should import from ``core.memory`` instead, which
re-exports the same classes through the canonical memory
facade. See docs/REPO_STRUCTURE_AUDIT.md cleanup item 3.
"""
from .short_term.cache import ShortTermCache
from .long_term.persistent_store import PersistentStore
from .vector_store.vector_db import VectorDB
from .embeddings.embedding_manager import EmbeddingManager

__all__ = ["ShortTermCache", "PersistentStore", "VectorDB", "EmbeddingManager"]
