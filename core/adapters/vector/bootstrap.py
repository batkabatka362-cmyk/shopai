"""Vector DB adapter bootstrap.

Single entry point that instantiates every vector database adapter
and registers it with ``AdapterRegistry``.

Usage::

    from core.adapters.vector.bootstrap import register_all
    register_all()

Weaviate requires a running instance (local Docker or Weaviate
Cloud) and the ``weaviate-client`` Python package. The adapter
still registers when not installed; the router silently skips it
via ``is_configured()``.
"""
from __future__ import annotations

from utils.logger import get_logger

from ..registry import AdapterRegistry, get_registry
from .pinecone import PineconeAdapter
from .qdrant import QdrantAdapter
from .weaviate import WeaviateAdapter

logger = get_logger("adapters.vector.bootstrap")


_VECTOR_ADAPTER_CLASSES = (
    PineconeAdapter,
    QdrantAdapter,
    WeaviateAdapter,
)


def register_all(
    registry: AdapterRegistry | None = None,
) -> dict[str, bool]:
    """Instantiate every vector DB adapter and register it.

    Returns a ``{adapter_name: is_configured}`` map.
    """
    reg = registry or get_registry()
    status: dict[str, bool] = {}

    for cls in _VECTOR_ADAPTER_CLASSES:
        try:
            adapter = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to instantiate %s: %s", cls.__name__, exc,
            )
            continue

        try:
            reg.register(adapter, replace=True)
            status[adapter.name] = adapter.is_configured()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "failed to register %s: %s", adapter.name, exc,
            )

    configured = sum(1 for v in status.values() if v)
    logger.info(
        "Vector DB adapters registered: %d total, %d configured",
        len(status), configured,
    )
    return status
