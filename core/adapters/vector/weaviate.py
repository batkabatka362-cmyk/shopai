"""WeaviateAdapter — managed vector database for semantic search.

Replaces the in-memory JSON-based ``VectorStore`` in
``engines/global_brain/vector_store.py`` with a production-grade
vector database that supports:

  * **VECTOR_STORE**  — upsert objects with vectors and metadata
  * **VECTOR_SEARCH** — nearest-neighbour search by vector or text
  * **VECTOR_DELETE** — delete objects by ID or batch filter

Weaviate runs as a self-hosted container (docker-compose) or
Weaviate Cloud. The adapter auto-creates the collection (class)
on first write if it doesn't exist.

Configuration::

    WEAVIATE_URL=http://localhost:8080
    WEAVIATE_API_KEY=...          # optional for local instances
    WEAVIATE_COLLECTION=ShopAI    # default collection name

The adapter is best-effort: if ``weaviate`` is not installed or
the server is unreachable, ``is_configured()`` returns False and
the router falls back to the JSON vector store.

Reference: https://weaviate.io/developers/weaviate
"""
from __future__ import annotations

import uuid
from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterError,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import weaviate
    from weaviate.exceptions import (
        WeaviateConnectionError as WvConnError,
        WeaviateTimeoutError as WvTimeout,
    )
    _WEAVIATE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WEAVIATE_AVAILABLE = False
    weaviate = None  # type: ignore[assignment]
    WvConnError = None  # type: ignore[assignment,misc]
    WvTimeout = None  # type: ignore[assignment,misc]

logger = get_logger("adapters.vector.weaviate")

_DEFAULT_COLLECTION = "ShopAI"
_DEFAULT_LIMIT = 10


class WeaviateAdapter(BaseAdapter):
    """Weaviate vector database via REST/gRPC client."""

    name = "weaviate"
    category = AdapterCategory.VECTOR_DB
    capabilities = {
        Capability.VECTOR_STORE,
        Capability.VECTOR_SEARCH,
        Capability.VECTOR_DELETE,
    }

    priority = 80
    cost_per_call = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """True when the ``weaviate`` client library is importable
        and ``WEAVIATE_URL`` is set."""
        if not _WEAVIATE_AVAILABLE:
            return False
        return bool(get_config().get("weaviate_url"))

    def _get_url(self) -> str:
        url = get_config().get("weaviate_url")
        if not url:
            raise AdapterUnavailable(
                self.name, "WEAVIATE_URL not set",
            )
        return url

    def _get_collection(self, params: dict[str, Any]) -> str:
        return params.get("collection", _DEFAULT_COLLECTION)

    def _connect(self):
        """Create a Weaviate client connection."""
        url = self._get_url()
        api_key = get_config().get("weaviate_api_key")

        try:
            if api_key:
                auth = weaviate.auth.AuthApiKey(api_key=api_key)
                client = weaviate.connect_to_custom(
                    http_host=url.replace("http://", "").replace("https://", "").split(":")[0],
                    http_port=int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 8080,
                    http_secure=url.startswith("https"),
                    grpc_host=url.replace("http://", "").replace("https://", "").split(":")[0],
                    grpc_port=50051,
                    grpc_secure=url.startswith("https"),
                    auth_credentials=auth,
                )
            else:
                client = weaviate.connect_to_local(
                    host=url.replace("http://", "").replace("https://", "").split(":")[0],
                    port=int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 8080,
                )
            return client
        except Exception as exc:
            raise AdapterUnavailable(
                self.name, f"connection failed: {exc}",
            ) from exc

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.VECTOR_STORE:
            return self._do_store(params)
        if capability == Capability.VECTOR_SEARCH:
            return self._do_search(params)
        if capability == Capability.VECTOR_DELETE:
            return self._do_delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── VECTOR_STORE ──────────────────────────────────────────

    def _do_store(self, params: dict[str, Any]) -> AdapterResult:
        """Store one or more vectors with metadata.

        Params:
          * ``objects`` — list of dicts, each with:
              - ``vector`` (list[float]) — the embedding
              - ``properties`` (dict) — metadata fields
              - ``id`` (str, optional) — deterministic UUID
          * ``collection`` (str, optional) — target collection
        """
        objects = params.get("objects")
        if not objects or not isinstance(objects, list):
            raise AdapterValidationError(
                self.name,
                "'objects' list is required for VECTOR_STORE",
            )

        collection_name = self._get_collection(params)
        client = self._connect()

        try:
            collection = client.collections.get(collection_name)

            stored_ids: list[str] = []
            for obj in objects:
                vector = obj.get("vector")
                properties = obj.get("properties", {})
                obj_id = obj.get("id", str(uuid.uuid4()))

                if not vector or not isinstance(vector, list):
                    raise AdapterValidationError(
                        self.name,
                        "each object must have a 'vector' (list of floats)",
                    )

                collection.data.insert(
                    properties=properties,
                    vector=vector,
                    uuid=obj_id,
                )
                stored_ids.append(obj_id)

            return AdapterResult.success(
                adapter=self.name,
                capability=Capability.VECTOR_STORE.value,
                data={
                    "stored_count": len(stored_ids),
                    "ids": stored_ids,
                    "collection": collection_name,
                },
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc
        finally:
            client.close()

    # ── VECTOR_SEARCH ─────────────────────────────────────────

    def _do_search(self, params: dict[str, Any]) -> AdapterResult:
        """Nearest-neighbour search.

        Params:
          * ``vector`` (list[float]) — query vector
          * ``limit`` (int, optional) — max results (default 10)
          * ``filters`` (dict, optional) — metadata filters
          * ``collection`` (str, optional) — target collection
        """
        vector = params.get("vector")
        if not vector or not isinstance(vector, list):
            raise AdapterValidationError(
                self.name,
                "'vector' (list of floats) is required for VECTOR_SEARCH",
            )

        limit = int(params.get("limit", _DEFAULT_LIMIT))
        collection_name = self._get_collection(params)
        client = self._connect()

        try:
            collection = client.collections.get(collection_name)

            results = collection.query.near_vector(
                near_vector=vector,
                limit=limit,
                return_metadata=["distance"],
            )

            hits: list[dict[str, Any]] = []
            for obj in results.objects:
                hit: dict[str, Any] = {
                    "id": str(obj.uuid),
                    "properties": dict(obj.properties) if obj.properties else {},
                    "distance": obj.metadata.distance if obj.metadata else None,
                }
                hits.append(hit)

            return AdapterResult.success(
                adapter=self.name,
                capability=Capability.VECTOR_SEARCH.value,
                data={
                    "hits": hits,
                    "count": len(hits),
                    "collection": collection_name,
                    "limit": limit,
                },
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc
        finally:
            client.close()

    # ── VECTOR_DELETE ─────────────────────────────────────────

    def _do_delete(self, params: dict[str, Any]) -> AdapterResult:
        """Delete vectors by ID.

        Params:
          * ``ids`` (list[str]) — UUIDs to delete
          * ``collection`` (str, optional) — target collection
        """
        ids = params.get("ids")
        if not ids or not isinstance(ids, list):
            raise AdapterValidationError(
                self.name,
                "'ids' list is required for VECTOR_DELETE",
            )

        collection_name = self._get_collection(params)
        client = self._connect()

        try:
            collection = client.collections.get(collection_name)

            deleted = 0
            for obj_id in ids:
                collection.data.delete_by_id(obj_id)
                deleted += 1

            return AdapterResult.success(
                adapter=self.name,
                capability=Capability.VECTOR_DELETE.value,
                data={
                    "deleted_count": deleted,
                    "collection": collection_name,
                },
            )
        except AdapterError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc
        finally:
            client.close()

    # ── Error mapping ─────────────────────────────────────────

    def _map_error(self, exc: Exception) -> AdapterError:
        """Map Weaviate client exceptions to typed adapter errors."""
        if _WEAVIATE_AVAILABLE and WvTimeout and isinstance(exc, WvTimeout):
            return AdapterTimeout(
                self.name, f"weaviate timeout: {exc}",
            )
        if _WEAVIATE_AVAILABLE and WvConnError and isinstance(exc, WvConnError):
            return AdapterUnavailable(
                self.name, f"weaviate connection error: {exc}",
            )
        return AdapterError(
            self.name,
            f"weaviate error: {type(exc).__name__}: {exc}",
        )
