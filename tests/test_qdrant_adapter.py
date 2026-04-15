"""Tests for the Qdrant vector DB adapter.

Real HTTP calls are forbidden — every test patches
``_http_request`` to return canned responses.

Coverage:
  * Metadata (name, category, capabilities, priority)
  * is_configured() via QDRANT_URL presence
  * Auth header injection (api-key only when set)
  * VECTOR_STORE: validation, Pinecone/Weaviate/Qdrant shapes,
    ID requirement, collection override
  * VECTOR_SEARCH: validation, happy path, limit, filter,
    score_threshold, payload normalisation under both keys
  * VECTOR_DELETE: validation, happy path
  * Capability dispatch rejects unsupported caps
  * Bootstrap registration + idempotency
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("WEAVIATE_URL", raising=False)
    monkeypatch.delenv("WEAVIATE_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure(monkeypatch, *, url="http://localhost:6333", key=None):
    monkeypatch.setenv("QDRANT_URL", url)
    if key is not None:
        monkeypatch.setenv("QDRANT_API_KEY", key)
    get_config().reload()


# ── Metadata ──────────────────────────────────────────────────


class TestQdrantMetadata:
    def test_metadata(self):
        from core.adapters.vector.qdrant import QdrantAdapter
        a = QdrantAdapter()
        assert a.name == "qdrant"
        assert a.category == AdapterCategory.VECTOR_DB
        assert Capability.VECTOR_STORE in a.capabilities
        assert Capability.VECTOR_SEARCH in a.capabilities
        assert Capability.VECTOR_DELETE in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0


# ── Configuration ─────────────────────────────────────────────


class TestQdrantConfiguration:
    def test_unconfigured_without_url(self):
        from core.adapters.vector.qdrant import QdrantAdapter
        assert not QdrantAdapter().is_configured()

    def test_configured_with_url(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        assert QdrantAdapter().is_configured()

    def test_url_trailing_slash_stripped(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch, url="http://localhost:6333/")
        a = QdrantAdapter()
        assert a._get_url() == "http://localhost:6333"

    def test_default_collection(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        assert a._get_collection({}) == "shopai"

    def test_collection_override_via_param(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        assert a._get_collection({"collection": "products"}) == "products"

    def test_collection_override_via_env(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        monkeypatch.setenv("QDRANT_COLLECTION", "reviews")
        get_config().reload()
        a = QdrantAdapter()
        assert a._get_collection({}) == "reviews"


# ── Auth header ───────────────────────────────────────────────


class TestQdrantAuth:
    def test_no_api_key_omits_header(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        headers = a._auth_headers()
        # Self-hosted instances run without auth — don't send
        # an empty api-key header (Qdrant's JWT parser rejects it).
        assert "api-key" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_api_key_header_present_when_set(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch, key="qd-secret-key")
        a = QdrantAdapter()
        headers = a._auth_headers()
        assert headers["api-key"] == "qd-secret-key"


# ── VECTOR_STORE ─────────────────────────────────────────────


class TestQdrantStore:
    def test_store_requires_points(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        result = a.execute(Capability.VECTOR_STORE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_store_pinecone_shape(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "vectors": [
                        {
                            "id": "a-1",
                            "vector": [0.1, 0.2, 0.3],
                            "metadata": {"title": "Product A"},
                        },
                    ],
                },
            )
        assert result.ok
        assert result.data["upserted_count"] == 1
        assert result.data["ids"] == ["a-1"]
        assert result.data["collection"] == "shopai"

        # Verify the request body mapped metadata → payload
        _method, url = mock_req.call_args[0][0], mock_req.call_args[0][1]
        assert _method == "PUT"
        assert url.endswith("/collections/shopai/points")
        sent_body = mock_req.call_args.kwargs["body"]
        assert sent_body["points"][0]["payload"] == {"title": "Product A"}
        assert sent_body["points"][0]["id"] == "a-1"

    def test_store_weaviate_shape(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "objects": [
                        {
                            "id": "w-1",
                            "vector": [0.4, 0.5],
                            "properties": {"sku": "ABC-123"},
                        },
                    ],
                },
            )
        assert result.ok
        sent_body = mock_req.call_args.kwargs["body"]
        assert sent_body["points"][0]["payload"] == {"sku": "ABC-123"}

    def test_store_native_qdrant_shape(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "points": [
                        {
                            "id": 42,
                            "vector": [0.9, 0.1],
                            "payload": {"tag": "native"},
                        },
                    ],
                },
            )
        assert result.ok
        sent_body = mock_req.call_args.kwargs["body"]
        assert sent_body["points"][0]["id"] == 42
        assert sent_body["points"][0]["payload"] == {"tag": "native"}

    def test_store_missing_id_rejected(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        result = a.execute(
            Capability.VECTOR_STORE,
            {"vectors": [{"vector": [0.1], "metadata": {}}]},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "id" in str(result.error).lower()

    def test_store_missing_vector_rejected(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        result = a.execute(
            Capability.VECTOR_STORE,
            {"vectors": [{"id": "x"}]},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_store_collection_override(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "collection": "catalog",
                    "vectors": [
                        {"id": "1", "vector": [0.1], "metadata": {}},
                    ],
                },
            )
        assert result.ok
        assert result.data["collection"] == "catalog"
        url = mock_req.call_args[0][1]
        assert "/collections/catalog/points" in url

    def test_store_uses_wait_true(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            a.execute(
                Capability.VECTOR_STORE,
                {"vectors": [{"id": "1", "vector": [0.1], "metadata": {}}]},
            )
        # Synchronous upsert — the next decision-loop step needs
        # the write visible, async would race.
        assert mock_req.call_args.kwargs["query"] == {"wait": "true"}


# ── VECTOR_SEARCH ────────────────────────────────────────────


class TestQdrantSearch:
    def test_search_requires_vector(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        result = a.execute(Capability.VECTOR_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_search_happy_path(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        raw = {
            "result": [
                {
                    "id": "p-1",
                    "score": 0.92,
                    "payload": {"title": "Alpha"},
                },
                {
                    "id": "p-2",
                    "score": 0.71,
                    "payload": {"title": "Beta"},
                },
            ],
        }
        with patch.object(a, "_http_request", return_value=raw):
            result = a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1, 0.2]},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["limit"] == 10
        assert result.data["hits"][0]["id"] == "p-1"
        assert result.data["hits"][0]["score"] == 0.92
        # Both Pinecone-style "metadata" and Weaviate-style
        # "properties" keys are populated so either caller works.
        assert result.data["hits"][0]["metadata"]["title"] == "Alpha"
        assert result.data["hits"][0]["properties"]["title"] == "Alpha"

    def test_search_with_limit(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"result": []},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1], "limit": 5},
            )
        assert result.ok
        assert result.data["limit"] == 5
        sent_body = mock_req.call_args.kwargs["body"]
        assert sent_body["limit"] == 5

    def test_search_with_filter(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        qdrant_filter = {"must": [{"key": "tag", "match": {"value": "vip"}}]}
        with patch.object(
            a, "_http_request", return_value={"result": []},
        ) as mock_req:
            a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1], "filter": qdrant_filter},
            )
        assert mock_req.call_args.kwargs["body"]["filter"] == qdrant_filter

    def test_search_with_score_threshold(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"result": []},
        ) as mock_req:
            a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1], "score_threshold": 0.8},
            )
        assert mock_req.call_args.kwargs["body"]["score_threshold"] == 0.8

    def test_search_top_k_alias(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"result": []},
        ) as mock_req:
            a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1], "top_k": 3},
            )
        # Pinecone-style top_k should work too.
        assert mock_req.call_args.kwargs["body"]["limit"] == 3


# ── VECTOR_DELETE ────────────────────────────────────────────


class TestQdrantDelete:
    def test_delete_requires_ids(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        result = a.execute(Capability.VECTOR_DELETE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_delete_happy_path(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()

        with patch.object(
            a, "_http_request", return_value={"status": "ok"},
        ) as mock_req:
            result = a.execute(
                Capability.VECTOR_DELETE,
                {"ids": ["p-1", "p-2", "p-3"]},
            )
        assert result.ok
        assert result.data["deleted_count"] == 3

        url = mock_req.call_args[0][1]
        assert url.endswith("/collections/shopai/points/delete")
        sent_body = mock_req.call_args.kwargs["body"]
        assert sent_body["points"] == ["p-1", "p-2", "p-3"]


# ── Dispatch ─────────────────────────────────────────────────


class TestQdrantDispatch:
    def test_unsupported_capability_rejected(self, monkeypatch):
        from core.adapters.vector.qdrant import QdrantAdapter
        _configure(monkeypatch)
        a = QdrantAdapter()
        # VECTOR_DB adapters don't speak BROWSER_SCREENSHOT.
        result = a.execute(Capability.BROWSER_SCREENSHOT, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── Bootstrap ────────────────────────────────────────────────


class TestVectorBootstrapIncludesQdrant:
    def test_register_all_adds_qdrant(self):
        from core.adapters.vector.bootstrap import register_all
        status = register_all()
        assert "qdrant" in status
        assert "weaviate" in status
        assert "pinecone" in status

    def test_register_all_idempotent(self):
        from core.adapters.vector.bootstrap import register_all
        register_all()
        register_all()
        qdrant_count = len([
            n for n in get_registry().names() if n == "qdrant"
        ])
        assert qdrant_count == 1
