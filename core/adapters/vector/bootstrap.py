"""Vector-store adapter bootstrap (stub: Weaviate/Pinecone/Qdrant not wired)."""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry

logger = get_logger("adapters.vector.bootstrap")


def register_all(registry: AdapterRegistry | None = None) -> dict[str, bool]:
    logger.debug("vector bootstrap: no adapters implemented")
    return {}
