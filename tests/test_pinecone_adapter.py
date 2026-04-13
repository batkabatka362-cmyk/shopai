"""Tests for the Pinecone vector DB adapter.

Real HTTP calls are forbidden — every test patches
``_http_post`` to return canned responses.
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


def _configure_pinecone(monkeypatch, *, key="pc-test-key"):
    monkeypatch.setenv("PINECONE_API_KEY", key)
    get_config().reload()


class TestPineconeMetadata:
    def test_metadata(self):
        from core.adapters.vector.pinecone import PineconeAdapter
        a = PineconeAdapter()
        assert a.name == "pinecone"
        assert a.category == AdapterCategory.VECTOR_DB
        assert Capability.VECTOR_STORE in a.capabilities
        assert Capability.VECTOR_SEARCH in a.capabilities
        assert Capability.VECTOR_DELETE in a.capabilities
        assert a.priority == 80

    def test_unconfigured_without_key(self):
        from core.adapters.vector.pinecone import PineconeAdapter
        assert not PineconeAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        assert PineconeAdapter().is_configured()


class TestPineconeAuth:
    def test_api_key_header(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch, key="pc-secret")
        a = PineconeAdapter()
        headers = a._auth_headers()
        assert headers["Api-Key"] == "pc-secret"


class TestPineconeStore:
    def test_store_requires_host(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        result = a.execute(
            Capability.VECTOR_STORE,
            {"vectors": [{"id": "1", "vector": [0.1, 0.2]}]},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_store_happy_path(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        raw = {"upsertedCount": 2}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.VECTOR_STORE,
                {
                    "host": "my-index-abc.svc.pinecone.io",
                    "vectors": [
                        {"id": "v1", "vector": [0.1, 0.2, 0.3], "metadata": {"text": "hello"}},
                        {"id": "v2", "vector": [0.4, 0.5, 0.6]},
                    ],
                },
            )

        assert result.ok
        assert result.data["upserted_count"] == 2


class TestPineconeSearch:
    def test_search_requires_host(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        result = a.execute(
            Capability.VECTOR_SEARCH,
            {"vector": [0.1, 0.2]},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_search_happy_path(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        raw = {
            "matches": [
                {"id": "v1", "score": 0.95, "metadata": {"text": "hello"}},
                {"id": "v2", "score": 0.80, "metadata": {"text": "world"}},
            ],
        }

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.VECTOR_SEARCH,
                {
                    "host": "my-index-abc.svc.pinecone.io",
                    "vector": [0.1, 0.2, 0.3],
                    "limit": 5,
                },
            )

        assert result.ok
        assert result.data["count"] == 2
        assert result.data["matches"][0]["score"] == 0.95


class TestPineconeDelete:
    def test_delete_requires_host(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        result = a.execute(
            Capability.VECTOR_DELETE,
            {"ids": ["v1"]},
        )
        assert not result.ok

    def test_delete_happy_path(self, monkeypatch):
        from core.adapters.vector.pinecone import PineconeAdapter
        _configure_pinecone(monkeypatch)
        a = PineconeAdapter()

        with patch.object(a, "_http_post", return_value={}):
            result = a.execute(
                Capability.VECTOR_DELETE,
                {
                    "host": "my-index-abc.svc.pinecone.io",
                    "ids": ["v1", "v2"],
                },
            )

        assert result.ok
        assert result.data["deleted_count"] == 2


class TestPineconeBootstrap:
    def test_bootstrap_includes_pinecone(self):
        from core.adapters.vector.bootstrap import register_all
        status = register_all()
        assert "pinecone" in status
        assert "weaviate" in status
