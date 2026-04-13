"""Vector database adapters.

Wraps vector databases behind ``BaseAdapter`` so the brain can
store, search, and delete vector embeddings via the smart router.

Capabilities:

  * ``VECTOR_STORE``   — store one or more vectors with metadata
  * ``VECTOR_SEARCH``  — nearest-neighbour search by vector or text
  * ``VECTOR_DELETE``  — delete vectors by ID or filter

Bootstrap::

    from core.adapters.vector.bootstrap import register_all
    register_all()
"""
from .weaviate import WeaviateAdapter

__all__ = ["WeaviateAdapter"]
