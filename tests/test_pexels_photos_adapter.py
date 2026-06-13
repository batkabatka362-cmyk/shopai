"""W963-169: PexelsPhotosAdapter tests."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from core.adapters.base import Capability
from core.adapters.errors import AdapterValidationError
from core.adapters.image.pexels_photos import (
    PexelsPhotosAdapter,
    _extract_pexels_photos,
)


class TestMetadata:
    def test_name(self):
        a = PexelsPhotosAdapter()
        assert a.name == "pexels_photos"

    def test_capabilities(self):
        a = PexelsPhotosAdapter()
        assert Capability.IMAGE_STOCK_SEARCH in a.capabilities

    def test_auth_header_no_bearer_prefix(self):
        a = PexelsPhotosAdapter()
        with patch.object(
            a, "_api_key", return_value="test_key",
        ):
            headers = a._auth_headers()
        assert headers["Authorization"] == "test_key"
        assert "Bearer" not in headers["Authorization"]


class TestSearch:
    def test_missing_query_rejects(self, monkeypatch):
        monkeypatch.setenv("PEXELS_API_KEY", "test_key")
        a = PexelsPhotosAdapter()
        result = a.execute(
            Capability.IMAGE_STOCK_SEARCH, {},
        )
        assert not result.ok
        assert isinstance(
            result.error, AdapterValidationError,
        )

    def test_search_happy_path(self, monkeypatch):
        monkeypatch.setenv("PEXELS_API_KEY", "test_key")
        a = PexelsPhotosAdapter()
        fake_resp = {
            "photos": [
                {
                    "id": 100,
                    "alt": "vitamin c serum bottle",
                    "width": 4000,
                    "height": 3000,
                    "photographer": "Test",
                    "url": (
                        "https://www.pexels.com/photo/100/"
                    ),
                    "src": {
                        "original": (
                            "https://x.com/o.jpg"
                        ),
                        "large2x": (
                            "https://x.com/l2x.jpg"
                        ),
                        "large": "https://x.com/l.jpg",
                        "medium": "https://x.com/m.jpg",
                        "small": "https://x.com/s.jpg",
                        "tiny": "https://x.com/t.jpg",
                    },
                },
            ],
        }
        with patch.object(
            a, "_http_get", return_value=fake_resp,
        ):
            result = a.execute(
                Capability.IMAGE_STOCK_SEARCH,
                {
                    "query": "vitamin c serum",
                    "limit": 1,
                    "orientation": "landscape",
                },
            )
        assert result.ok
        photos = result.data["photos"]
        assert len(photos) == 1
        p = photos[0]
        assert p["photo_id"] == "100"
        assert p["alt"] == "vitamin c serum bottle"
        # All size variants surfaced
        assert p["url_large2x"] == "https://x.com/l2x.jpg"
        assert p["url_large"] == "https://x.com/l.jpg"
        assert p["url_original"] == "https://x.com/o.jpg"

    def test_limit_clamped(self, monkeypatch):
        """limit must clamp to 1..80 (Pexels API ceiling)."""
        monkeypatch.setenv("PEXELS_API_KEY", "test_key")
        a = PexelsPhotosAdapter()
        captured: list[dict] = []

        def fake_get(url, *, params=None):
            captured.append(dict(params or {}))
            return {"photos": []}

        with patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.IMAGE_STOCK_SEARCH,
                {"query": "x", "limit": 999},
            )
        assert captured[0]["per_page"] == 80

    def test_invalid_orientation_dropped(self, monkeypatch):
        """Invalid orientation must not reach the API."""
        monkeypatch.setenv("PEXELS_API_KEY", "test_key")
        a = PexelsPhotosAdapter()
        captured: list[dict] = []

        def fake_get(url, *, params=None):
            captured.append(dict(params or {}))
            return {"photos": []}

        with patch.object(
            a, "_http_get", side_effect=fake_get,
        ):
            a.execute(
                Capability.IMAGE_STOCK_SEARCH,
                {
                    "query": "x",
                    "orientation": "diagonal",
                },
            )
        assert "orientation" not in captured[0]


class TestExtract:
    def test_handles_non_dict(self):
        assert _extract_pexels_photos(None) == []
        assert _extract_pexels_photos("abc") == []

    def test_skips_non_dict_photo_entries(self):
        result = _extract_pexels_photos({
            "photos": [
                {
                    "id": 1, "alt": "ok",
                    "src": {"original": "u"},
                },
                "not a dict",
                None,
            ],
        })
        assert len(result) == 1
        assert result[0]["photo_id"] == "1"

    def test_missing_src_defaults_empty_urls(self):
        result = _extract_pexels_photos({
            "photos": [{"id": 1, "alt": "ok"}],
        })
        assert result[0]["url_original"] == ""
        assert result[0]["url_large2x"] == ""


class TestBootstrap:
    def test_pexels_photos_registers(self, monkeypatch):
        from core.adapters.image.bootstrap import register_all
        from core.adapters.registry import AdapterRegistry

        reg = AdapterRegistry()
        status = register_all(registry=reg)
        assert "pexels_photos" in status

    def test_router_picks_pexels_for_image_search(
        self, monkeypatch,
    ):
        from core.adapters.image.bootstrap import register_all
        from core.adapters.registry import AdapterRegistry
        from core.adapters.router import SmartRouter

        reg = AdapterRegistry()
        register_all(registry=reg)
        monkeypatch.setenv("PEXELS_API_KEY", "test_key_12345")

        router = SmartRouter(registry=reg)
        chosen = router.route(Capability.IMAGE_STOCK_SEARCH)
        assert chosen.name == "pexels_photos"
