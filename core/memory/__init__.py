"""``core.memory`` — canonical import path for ShopAI memory.

The 4 storage primitives (ShortTermCache, PersistentStore,
VectorDB, EmbeddingManager) physically live in the legacy
top-level ``memory/`` package. Older code imports them from
there; new code should import from ``core.memory`` so every
memory surface flows through a single facade (matching the
12-concept layout in docs/FOLDER_REORG_PLAN.md).

Both paths keep working — this is the non-breaking half of
the C3 consolidation the 2026-04-20 audit called for.
"""
from .memory_manager import MemoryManager
from .memory_router import MemoryRouter

# Re-export the 4 legacy storage primitives so new code can
# use a single canonical path. The underlying classes still
# live in ``memory/`` until a later migration physically
# moves them — importing from either location produces the
# same class object.
try:
    from memory.short_term.cache import ShortTermCache
except Exception:  # noqa: BLE001 — keep facade import-safe
    ShortTermCache = None  # type: ignore[assignment]
try:
    from memory.long_term.persistent_store import (
        PersistentStore,
    )
except Exception:  # noqa: BLE001
    PersistentStore = None  # type: ignore[assignment]
try:
    from memory.vector_store.vector_db import VectorDB
except Exception:  # noqa: BLE001
    VectorDB = None  # type: ignore[assignment]
try:
    from memory.embeddings.embedding_manager import (
        EmbeddingManager,
    )
except Exception:  # noqa: BLE001
    EmbeddingManager = None  # type: ignore[assignment]

__all__ = [
    "MemoryManager",
    "MemoryRouter",
    "ShortTermCache",
    "PersistentStore",
    "VectorDB",
    "EmbeddingManager",
]
