"""PineconeAdapter — Pinecone managed vector database.

Pinecone is a fully managed vector database optimized for
machine learning applications. Unlike Weaviate (self-hosted or
cloud), Pinecone is always cloud-hosted with zero ops.

Capabilities:

  * **VECTOR_STORE** — upsert vectors with metadata
  * **VECTOR_SEARCH** — nearest-neighbor search by vector
  * **VECTOR_DELETE** — delete vectors by IDs

Authentication: API key in header.
Free tier: 1 index, 100K vectors, 1 serverless pod.
Pricing: from $25/month for Starter.

Reference: https://docs.pinecone.io/reference/api/introduction
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
    AdapterError,
    AdapterNotConfigured,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


class PineconeAdapter(BaseAdapter):
    name = "pinecone"
    category = AdapterCategory.VECTOR_DB
    capabilities = {
        Capability.VECTOR_STORE,
        Capability.VECTOR_SEARCH,
        Capability.VECTOR_DELETE,
    }

    config_alias = "pinecone"
    priority = 80
    cost_per_call = 0.0
    timeout: float = 20.0

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            raise AdapterNotConfigured(
                self.name, "missing PINECONE_API_KEY",
            )
        return key

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Api-Key": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

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

    # ── Store (upsert) ─────────────────────────────────────────

    def _do_store(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        host = params.get("host")
        if not host:
            raise AdapterValidationError(
                self.name, "'host' (index host URL) is required",
            )
        vectors = params.get("vectors")
        if not vectors or not isinstance(vectors, list):
            raise AdapterValidationError(
                self.name, "'vectors' list is required",
            )

        # Build upsert payload
        pinecone_vectors = []
        for v in vectors:
            pv: dict[str, Any] = {
                "id": v["id"],
                "values": v["vector"],
            }
            if v.get("metadata"):
                pv["metadata"] = v["metadata"]
            pinecone_vectors.append(pv)

        namespace = params.get("namespace", "")
        body: dict[str, Any] = {"vectors": pinecone_vectors}
        if namespace:
            body["namespace"] = namespace

        url = f"https://{host}/vectors/upsert"
        raw = self._http_post(url, body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "upserted_count": raw.get("upsertedCount", len(vectors)),
            },
            raw=raw,
        )

    # ── Search (query) ─────────────────────────────────────────

    def _do_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        host = params.get("host")
        if not host:
            raise AdapterValidationError(
                self.name, "'host' (index host URL) is required",
            )
        vector = params.get("vector")
        if not vector:
            raise AdapterValidationError(
                self.name, "'vector' (query vector) is required",
            )

        top_k = params.get("limit", params.get("top_k", 10))
        namespace = params.get("namespace", "")
        body: dict[str, Any] = {
            "vector": vector,
            "topK": top_k,
            "includeMetadata": params.get("include_metadata", True),
        }
        if namespace:
            body["namespace"] = namespace
        if params.get("filter"):
            body["filter"] = params["filter"]

        url = f"https://{host}/query"
        raw = self._http_post(url, body)

        matches = []
        for m in raw.get("matches", []):
            matches.append({
                "id": m.get("id", ""),
                "score": m.get("score", 0.0),
                "metadata": m.get("metadata", {}),
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"matches": matches, "count": len(matches)},
            raw=raw,
        )

    # ── Delete ─────────────────────────────────────────────────

    def _do_delete(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        host = params.get("host")
        if not host:
            raise AdapterValidationError(
                self.name, "'host' (index host URL) is required",
            )
        ids = params.get("ids")
        if not ids or not isinstance(ids, list):
            raise AdapterValidationError(
                self.name, "'ids' list is required",
            )

        namespace = params.get("namespace", "")
        body: dict[str, Any] = {"ids": ids}
        if namespace:
            body["namespace"] = namespace

        url = f"https://{host}/vectors/delete"
        raw = self._http_post(url, body)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"deleted_count": len(ids)},
            raw=raw,
        )

    # ── HTTP helper ────────────────────────────────────────────

    def _http_post(self, url: str, body: dict[str, Any]) -> Any:
        if not _REQUESTS_AVAILABLE:
            from ..errors import AdapterUnavailable
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.post(
                url, json=body, headers=self._auth_headers(),
                timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            from ..errors import AdapterTimeout
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            from ..errors import AdapterUnavailable
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name, f"HTTP POST failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                from ..errors import AdapterAuthError
                raise AdapterAuthError(self.name, snippet)
            raise AdapterError(
                self.name,
                f"Pinecone returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
