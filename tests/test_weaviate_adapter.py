"""Tests for the Weaviate vector DB adapter with mocked client.

Weaviate is an optional dependency — tests mock all client
interactions so the suite runs without ``weaviate-client``.

Coverage:

  * WeaviateAdapter metadata (name, category, capabilities)
  * is_configured() checks weaviate availability + WEAVIATE_URL
  * VECTOR_STORE: validation, happy path, multiple objects
  * VECTOR_SEARCH: validation, happy path, limit param
  * VECTOR_DELETE: validation, happy path
  * Capability enum values exist
  * Bootstrap registration
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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
from core.adapters.errors import AdapterError


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
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


# ── Helpers ────────────────────────────────────────────────


def _get_adapter_class():
    from core.adapters.vector.weaviate import WeaviateAdapter
    return WeaviateAdapter


def _mock_collection():
    """Build a mock Weaviate collection."""
    collection = MagicMock()
    collection.data.insert.return_value = None
    collection.data.delete_by_id.return_value = None
    return collection


def _mock_client(collection=None):
    """Build a mock Weaviate client."""
    if collection is None:
        collection = _mock_collection()
    client = MagicMock()
    client.collections.get.return_value = collection
    return client


def _patch_weaviate(client=None, monkeypatch=None):
    """Patch ``_connect`` and ``is_configured`` for tests."""
    if client is None:
        client = _mock_client()

    cls = _get_adapter_class()
    return (
        patch.object(cls, "_connect", return_value=client),
        patch.object(cls, "is_configured", return_value=True),
    )


# ── Capability enum ────────────────────────────────────────


class TestVectorCapabilities:
    def test_capabilities_exist(self):
        assert Capability("vector_store") is Capability.VECTOR_STORE
        assert Capability("vector_search") is Capability.VECTOR_SEARCH
        assert Capability("vector_delete") is Capability.VECTOR_DELETE

    def test_vector_db_category_exists(self):
        assert AdapterCategory("vector_db") is AdapterCategory.VECTOR_DB


# ── Metadata ───────────────────────────────────────────────


class TestWeaviateMetadata:
    def test_metadata(self):
        a = _get_adapter_class()()
        assert a.name == "weaviate"
        assert a.category == AdapterCategory.VECTOR_DB
        assert Capability.VECTOR_STORE in a.capabilities
        assert Capability.VECTOR_SEARCH in a.capabilities
        assert Capability.VECTOR_DELETE in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0


# ── Configuration ──────────────────────────────────────────


class TestWeaviateConfiguration:
    def test_unconfigured_without_url(self):
        a = _get_adapter_class()()
        assert not a.is_configured()

    def test_configured_with_url(self, monkeypatch):
        # Weaviate also needs the library to be importable.
        # We test the URL check by patching the module-level flag.
        from core.adapters.vector import weaviate as wv_mod
        monkeypatch.setenv("WEAVIATE_URL", "http://localhost:8080")
        get_config().reload()
        with patch.object(wv_mod, "_WEAVIATE_AVAILABLE", True):
            a = _get_adapter_class()()
            assert a.is_configured()


# ── VECTOR_STORE ──────────────────────────────────────────


class TestVectorStore:
    def test_store_requires_objects(self):
        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate()
        with p1, p2:
            result = a.execute(Capability.VECTOR_STORE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_store_requires_vector_in_objects(self):
        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate()
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_STORE,
                {"objects": [{"properties": {"title": "test"}}]},
            )
        assert not result.ok

    def test_store_happy_path(self):
        collection = _mock_collection()
        client = _mock_client(collection)
        a = _get_adapter_class()()

        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "objects": [
                        {
                            "vector": [0.1, 0.2, 0.3],
                            "properties": {"title": "Test doc"},
                            "id": "abc-123",
                        },
                    ],
                },
            )

        assert result.ok
        assert result.data["stored_count"] == 1
        assert result.data["ids"] == ["abc-123"]
        assert result.data["collection"] == "ShopAI"
        collection.data.insert.assert_called_once()

    def test_store_multiple_objects(self):
        collection = _mock_collection()
        client = _mock_client(collection)
        a = _get_adapter_class()()

        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "objects": [
                        {"vector": [0.1, 0.2], "properties": {"n": 1}},
                        {"vector": [0.3, 0.4], "properties": {"n": 2}},
                        {"vector": [0.5, 0.6], "properties": {"n": 3}},
                    ],
                },
            )

        assert result.ok
        assert result.data["stored_count"] == 3
        assert len(result.data["ids"]) == 3
        assert collection.data.insert.call_count == 3

    def test_store_custom_collection(self):
        collection = _mock_collection()
        client = _mock_client(collection)
        a = _get_adapter_class()()

        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "collection": "Products",
                    "objects": [{"vector": [0.1], "properties": {}}],
                },
            )

        assert result.ok
        assert result.data["collection"] == "Products"
        client.collections.get.assert_called_with("Products")


# ── VECTOR_SEARCH ─────────────────────────────────────────


class TestVectorSearch:
    def test_search_requires_vector(self):
        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate()
        with p1, p2:
            result = a.execute(Capability.VECTOR_SEARCH, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_search_happy_path(self):
        collection = _mock_collection()
        client = _mock_client(collection)

        # Build mock search results
        obj1 = MagicMock()
        obj1.uuid = "id-1"
        obj1.properties = {"title": "Product A"}
        obj1.metadata.distance = 0.12

        obj2 = MagicMock()
        obj2.uuid = "id-2"
        obj2.properties = {"title": "Product B"}
        obj2.metadata.distance = 0.45

        search_result = MagicMock()
        search_result.objects = [obj1, obj2]
        collection.query.near_vector.return_value = search_result

        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1, 0.2, 0.3]},
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["hits"][0]["id"] == "id-1"
        assert result.data["hits"][0]["distance"] == 0.12
        assert result.data["hits"][1]["properties"]["title"] == "Product B"

    def test_search_with_limit(self):
        collection = _mock_collection()
        client = _mock_client(collection)
        search_result = MagicMock()
        search_result.objects = []
        collection.query.near_vector.return_value = search_result

        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_SEARCH,
                {"vector": [0.1], "limit": 5},
            )

        assert result.ok
        assert result.data["limit"] == 5
        collection.query.near_vector.assert_called_once()
        call_kwargs = collection.query.near_vector.call_args[1]
        assert call_kwargs["limit"] == 5


# ── VECTOR_DELETE ─────────────────────────────────────────


class TestVectorDelete:
    def test_delete_requires_ids(self):
        a = _get_adapter_class()()
        p1, p2 = _patch_weaviate()
        with p1, p2:
            result = a.execute(Capability.VECTOR_DELETE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_delete_happy_path(self):
        collection = _mock_collection()
        client = _mock_client(collection)
        a = _get_adapter_class()()

        p1, p2 = _patch_weaviate(client)
        with p1, p2:
            result = a.execute(
                Capability.VECTOR_DELETE,
                {"ids": ["id-1", "id-2"]},
            )

        assert result.ok
        assert result.data["deleted_count"] == 2
        assert collection.data.delete_by_id.call_count == 2


# ── Bootstrap ──────────────────────────────────────────────


class TestVectorBootstrap:
    def test_register_all_adds_weaviate(self):
        from core.adapters.vector.bootstrap import register_all
        status = register_all()
        assert "weaviate" in status

    def test_register_all_idempotent(self):
        from core.adapters.vector.bootstrap import register_all
        register_all()
        register_all()
        weaviate_count = len([
            n for n in get_registry().names()
            if n == "weaviate"
        ])
        assert weaviate_count == 1
