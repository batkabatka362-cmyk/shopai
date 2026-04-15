"""QdrantAdapter — Qdrant vector database (self-hosted or Cloud).

Qdrant is an open-source vector database written in Rust. Unlike
Pinecone (always cloud-hosted) and Weaviate (which requires a
heavyweight Python client with gRPC), Qdrant exposes a simple
HTTP/JSON REST API that works identically against:

  * a local Docker container (``docker run -p 6333:6333 qdrant/qdrant``)
  * Qdrant Cloud (managed, requires ``api-key`` header)

Capabilities:

  * **VECTOR_STORE**  — upsert points with vectors and payloads
  * **VECTOR_SEARCH** — nearest-neighbour search by vector
  * **VECTOR_DELETE** — delete points by ID list

Configuration::

    QDRANT_URL=http://localhost:6333        # required
    QDRANT_API_KEY=...                      # optional (Cloud only)
    QDRANT_COLLECTION=shopai                # default collection

Shape note: Qdrant's REST API uses ``points`` (not ``vectors``)
and ``payload`` (not ``metadata``). The adapter normalises both
to the common ShopAI shape — callers pass ``vectors=[...]``
with ``metadata={...}`` just like Pinecone, and the adapter maps
internally. Callers that already speak Qdrant-native shapes
(``points=[...]`` with ``payload={...}``) also work.

Reference: https://qdrant.tech/documentation/concepts/points/
"""
from __future__ import annotations

from typing import Any

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


_DEFAULT_COLLECTION = "shopai"
_DEFAULT_LIMIT = 10


class QdrantAdapter(BaseAdapter):
    """Qdrant vector database via REST API."""

    name = "qdrant"
    category = AdapterCategory.VECTOR_DB
    capabilities = {
        Capability.VECTOR_STORE,
        Capability.VECTOR_SEARCH,
        Capability.VECTOR_DELETE,
    }

    priority = 80
    cost_per_call = 0.0  # Self-hosted is free; Cloud is flat-rate.
    timeout: float = 20.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """True when the ``requests`` library is importable and
        ``QDRANT_URL`` is set. API key is optional — self-hosted
        instances run without auth."""
        if not _REQUESTS_AVAILABLE:
            return False
        return bool(get_config().get("qdrant_url"))

    def _get_url(self) -> str:
        url = get_config().get("qdrant_url")
        if not url:
            raise AdapterNotConfigured(
                self.name, "QDRANT_URL not set",
            )
        # Trim trailing slash so url-joining stays predictable.
        return str(url).rstrip("/")

    def _get_collection(self, params: dict[str, Any]) -> str:
        return (
            params.get("collection")
            or get_config().get("qdrant_collection")
            or _DEFAULT_COLLECTION
        )

    def _auth_headers(self) -> dict[str, str]:
        """Qdrant Cloud requires ``api-key``. Self-hosted
        instances can run without it — the header is omitted
        rather than sent empty (empty strings fail JWT parsers)."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_key = get_config().get("qdrant_api_key")
        if api_key:
            headers["api-key"] = api_key
        return headers

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        dispatch = {
            Capability.VECTOR_STORE: self._do_store,
            Capability.VECTOR_SEARCH: self._do_search,
            Capability.VECTOR_DELETE: self._do_delete,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── VECTOR_STORE (upsert) ─────────────────────────────────

    def _do_store(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Upsert one or more points.

        Accepts either the Pinecone-style shape::

            {"vectors": [{"id": "a", "vector": [...], "metadata": {...}}]}

        or the Weaviate-style shape::

            {"objects": [{"id": "a", "vector": [...], "properties": {...}}]}

        or the native Qdrant shape::

            {"points": [{"id": "a", "vector": [...], "payload": {...}}]}
        """
        points = self._normalise_points(params)
        if not points:
            raise AdapterValidationError(
                self.name,
                "one of 'points' / 'vectors' / 'objects' is required",
            )

        collection = self._get_collection(params)
        url = f"{self._get_url()}/collections/{collection}/points"
        # wait=true makes the upsert synchronous — the caller
        # sees the write confirmed before the adapter returns.
        # For a decision-loop where the next step immediately
        # queries what was just written, async would lose data.
        params_q = {"wait": "true"}
        body = {"points": points}

        raw = self._http_request(
            "PUT", url, body=body, query=params_q,
        )

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "upserted_count": len(points),
                "ids": [p["id"] for p in points],
                "collection": collection,
            },
            raw=raw,
        )

    # ── VECTOR_SEARCH ─────────────────────────────────────────

    def _do_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Nearest-neighbour search.

        Params:
          * ``vector``     (list[float]) — query vector (required)
          * ``limit``      (int)         — max results (default 10)
          * ``filter``     (dict)        — native Qdrant filter
          * ``collection`` (str)         — override collection
          * ``with_payload`` (bool)      — return payload (default True)
        """
        vector = params.get("vector")
        if not vector or not isinstance(vector, list):
            raise AdapterValidationError(
                self.name,
                "'vector' (list of floats) is required for VECTOR_SEARCH",
            )

        limit = int(params.get("limit", params.get("top_k", _DEFAULT_LIMIT)))
        collection = self._get_collection(params)
        url = (
            f"{self._get_url()}/collections/{collection}/points/search"
        )

        body: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": bool(params.get("with_payload", True)),
        }
        if params.get("filter"):
            body["filter"] = params["filter"]
        score_threshold = params.get("score_threshold")
        if score_threshold is not None:
            body["score_threshold"] = float(score_threshold)

        raw = self._http_request("POST", url, body=body)

        result = (raw or {}).get("result") or []
        hits: list[dict[str, Any]] = []
        for item in result:
            hits.append({
                "id": item.get("id"),
                "score": float(item.get("score", 0.0) or 0.0),
                # Normalise Qdrant's ``payload`` under both keys
                # so callers written against Pinecone (metadata)
                # or Weaviate (properties) work unchanged.
                "metadata": dict(item.get("payload") or {}),
                "properties": dict(item.get("payload") or {}),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "hits": hits,
                "count": len(hits),
                "collection": collection,
                "limit": limit,
            },
            raw=raw,
        )

    # ── VECTOR_DELETE ─────────────────────────────────────────

    def _do_delete(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Delete points by ID list.

        Params:
          * ``ids``        (list) — point IDs (ints or UUID strings)
          * ``collection`` (str)  — override collection
        """
        ids = params.get("ids")
        if not ids or not isinstance(ids, list):
            raise AdapterValidationError(
                self.name, "'ids' list is required for VECTOR_DELETE",
            )

        collection = self._get_collection(params)
        url = (
            f"{self._get_url()}/collections/{collection}/points/delete"
        )
        params_q = {"wait": "true"}
        body = {"points": list(ids)}

        raw = self._http_request(
            "POST", url, body=body, query=params_q,
        )

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "deleted_count": len(ids),
                "collection": collection,
            },
            raw=raw,
        )

    # ── Point normalisation ───────────────────────────────────

    def _normalise_points(
        self, params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Accept Pinecone/Weaviate/Qdrant-shaped inputs and
        emit a list of Qdrant-native point dicts.

        Each result has exactly: ``id``, ``vector``, ``payload``.
        Missing IDs are rejected — Qdrant requires explicit IDs
        (unlike Weaviate which auto-generates UUIDs), and
        silently minting UUIDs here would make repeated upserts
        create duplicates instead of updating.
        """
        raw_list: list[Any] = []
        if params.get("points"):
            raw_list = list(params["points"])
        elif params.get("vectors"):
            raw_list = list(params["vectors"])
        elif params.get("objects"):
            raw_list = list(params["objects"])

        out: list[dict[str, Any]] = []
        for i, item in enumerate(raw_list):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name,
                    f"point #{i} must be a dict, got {type(item).__name__}",
                )

            vec = item.get("vector")
            if not vec or not isinstance(vec, list):
                raise AdapterValidationError(
                    self.name,
                    f"point #{i} must have a 'vector' (list of floats)",
                )

            pid = item.get("id")
            if pid is None:
                raise AdapterValidationError(
                    self.name,
                    f"point #{i} must have an 'id' (int or UUID string)",
                )

            # Accept whichever key the caller used for metadata.
            # Precedence: explicit payload > metadata > properties.
            payload = (
                item.get("payload")
                if item.get("payload") is not None
                else item.get("metadata")
                if item.get("metadata") is not None
                else item.get("properties")
                if item.get("properties") is not None
                else {}
            )
            if not isinstance(payload, dict):
                raise AdapterValidationError(
                    self.name,
                    f"point #{i} payload must be a dict",
                )

            out.append({
                "id": pid,
                "vector": list(vec),
                "payload": dict(payload),
            })

        return out

    # ── HTTP helper ───────────────────────────────────────────

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.request(
                method, url,
                json=body,
                params=query,
                headers=self._auth_headers(),
                timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"HTTP {method} failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(self.name, snippet)
            raise AdapterError(
                self.name,
                f"Qdrant returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
