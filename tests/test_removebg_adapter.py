"""Tests for the Remove.bg image adapter.

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
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("REMOVEBG_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_removebg(monkeypatch, *, key="rbg-test-key"):
    monkeypatch.setenv("REMOVEBG_API_KEY", key)
    get_config().reload()


class TestRemoveBgMetadata:
    def test_metadata(self):
        from core.adapters.image.removebg import RemoveBgAdapter
        a = RemoveBgAdapter()
        assert a.name == "removebg"
        assert a.category == AdapterCategory.IMAGE_GEN
        assert Capability.OPTIMIZE_IMAGE in a.capabilities
        assert Capability.GENERATE_IMAGE not in a.capabilities
        assert a.priority == 85

    def test_unconfigured_without_key(self):
        from core.adapters.image.removebg import RemoveBgAdapter
        assert not RemoveBgAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        assert RemoveBgAdapter().is_configured()


class TestRemoveBgAuth:
    def test_api_key_header(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch, key="my-rbg-key")
        a = RemoveBgAdapter()
        # Auth is in _execute body, check _api_key works
        assert a._api_key() == "my-rbg-key"


class TestRemoveBgOptimize:
    def test_remove_bg_with_base64(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        a = RemoveBgAdapter()

        raw = {"data": {"result_b64": "transparent_image_b64=="}}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.OPTIMIZE_IMAGE,
                {"image_base64": "original_product_b64=="},
            )

        assert result.ok
        assert result.data["action"] == "remove_background"
        assert result.data["image_base64"] == "transparent_image_b64=="
        assert result.data["has_result"] is True

        # Verify POST body
        body = mocked.call_args[0][1]
        assert body["image_file_b64"] == "original_product_b64=="

    def test_remove_bg_with_url(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        a = RemoveBgAdapter()

        raw = {"data": {"result_b64": "result=="}}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            result = a.execute(
                Capability.OPTIMIZE_IMAGE,
                {"image_url": "https://example.com/product.jpg"},
            )

        assert result.ok
        body = mocked.call_args[0][1]
        assert body["image_url"] == "https://example.com/product.jpg"

    def test_requires_image_input(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        a = RemoveBgAdapter()

        result = a.execute(Capability.OPTIMIZE_IMAGE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_rejects_generate_image(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        a = RemoveBgAdapter()

        result = a.execute(
            Capability.GENERATE_IMAGE,
            {"prompt": "test"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_bg_color_passed(self, monkeypatch):
        from core.adapters.image.removebg import RemoveBgAdapter
        _configure_removebg(monkeypatch)
        a = RemoveBgAdapter()

        raw = {"data": {"result_b64": "x=="}}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.OPTIMIZE_IMAGE,
                {"image_base64": "orig==", "bg_color": "#FFFFFF"},
            )

        body = mocked.call_args[0][1]
        assert body["bg_color"] == "#FFFFFF"


class TestRemoveBgBootstrap:
    def test_register_all_includes_removebg(self):
        from core.adapters.image.bootstrap import register_all
        status = register_all()
        assert "removebg" in status

    def test_router_finds_removebg_for_optimize(self, monkeypatch):
        from core.adapters.image.bootstrap import register_all
        _configure_removebg(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.OPTIMIZE_IMAGE)
        assert chosen.name == "removebg"
