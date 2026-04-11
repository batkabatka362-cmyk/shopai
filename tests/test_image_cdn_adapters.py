"""Regression tests for the image-CDN adapter family.

Wave 1 extension — ImageKit only.

Real HTTP calls are forbidden — every test patches the
adapter's ``_http_post`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes OPTIMIZE_IMAGE
  * ImageCdnBaseAdapter validates inputs (source_url required +
    http(s) scheme, file_name required + length cap, tags type)
    and rejects unknown capabilities
  * ImageKitAdapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires IMAGEKIT_PRIVATE_KEY
        - _optimize_url points at /api/v1/files/upload
        - _auth_headers use HTTP Basic with the private key +
          empty password + form Content-Type
        - payload: file, fileName, folder, tags, flags,
          transformation_pre encoded as JSON
        - parse extracts url/fileId/name/size/dimensions/etc.
        - parse non-dict raises AdapterError
        - parse missing url raises AdapterError
        - happy path captures url + flat cost
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes OPTIMIZE_IMAGE to imagekit when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome
"""
from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterValidationError,
    Capability,
    NoAdapterAvailable,
    get_config,
    get_metrics,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Clear ImageKit env + every adapter singleton between tests."""
    for var in (
        "IMAGEKIT_PUBLIC_KEY",
        "IMAGEKIT_PRIVATE_KEY",
        "FIRECRAWL_API_KEY",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "OPENAI_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "DEEPL_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_imagekit(monkeypatch) -> str:
    key = "private_test_xxxxxxxxxxxxxx"
    monkeypatch.setenv("IMAGEKIT_PRIVATE_KEY", key)
    monkeypatch.setenv("IMAGEKIT_PUBLIC_KEY", "public_test_xxxx")
    get_config().reload()
    return key


_VALID_OPTIMIZE = {
    "source_url": "https://cdn.shop.example.com/img/product-1.jpg",
    "file_name": "product-1.jpg",
    "folder": "/products",
    "tags": ["product", "wave1"],
}


# ── Capability enum ─────────────────────────────────────────


class TestImageCdnCapabilities:
    def test_optimize_image_capability_exists(self):
        assert Capability("optimize_image") is Capability.OPTIMIZE_IMAGE


# ── ImageCdnBaseAdapter validation ──────────────────────────


class TestImageCdnBaseValidation:
    def test_source_url_required(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE, {"file_name": "x.jpg"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "source_url" in result.error.reason

    def test_source_url_must_be_http(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {
                "source_url": "ftp://files.example.com/a.jpg",
                "file_name": "a.jpg",
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "http" in result.error.reason.lower()

    def test_source_url_must_have_host(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {"source_url": "https://", "file_name": "a.jpg"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_file_name_required(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {"source_url": "https://x.example.com/a.jpg"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "file_name" in result.error.reason

    def test_file_name_too_long(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {
                "source_url": "https://x.example.com/a.jpg",
                "file_name": "x" * 1_025,
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_tags_wrong_type_rejected(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {
                "source_url": "https://x.example.com/a.jpg",
                "file_name": "a.jpg",
                "tags": "not-a-list",
            },
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── ImageKitAdapter ─────────────────────────────────────────


class TestImageKitAdapter:
    def test_metadata(self):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        a = ImageKitAdapter()
        assert a.name == "imagekit"
        assert a.category == AdapterCategory.IMAGE_CDN
        assert Capability.OPTIMIZE_IMAGE in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0

    def test_unconfigured_without_key(self):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        assert not ImageKitAdapter().is_configured()

    def test_configured_with_private_key(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        assert ImageKitAdapter().is_configured()

    def test_optimize_url(self):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        a = ImageKitAdapter()
        assert a._optimize_url() == (
            "https://upload.imagekit.io/api/v1/files/upload"
        )

    def test_auth_headers_basic_with_empty_password(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        key = _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        headers = a._auth_headers()

        expected_token = base64.b64encode(
            f"{key}:".encode("utf-8"),
        ).decode("ascii")
        assert headers["Authorization"] == f"Basic {expected_token}"
        assert headers["Content-Type"] == (
            "application/x-www-form-urlencoded"
        )
        assert headers["Accept"] == "application/json"

    def test_payload_basic(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
        })
        assert ("file", "https://x.example.com/a.jpg") in body
        assert ("fileName", "a.jpg") in body
        assert not any(k == "folder" for k, _ in body)
        assert not any(k == "tags" for k, _ in body)

    def test_payload_with_folder_and_tags(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
            "folder": "/products",
            "tags": ["a", "b", "c"],
        })
        assert ("folder", "/products") in body
        assert ("tags", "a,b,c") in body

    def test_payload_use_unique_filename_flag(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
            "use_unique_filename": True,
        })
        assert ("useUniqueFileName", "true") in body

    def test_payload_overwrite_flag(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
            "overwrite": False,
        })
        assert ("overwriteFile", "false") in body

    def test_payload_transformation_pre_json_encoded(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
            "transformation_pre": "w-1600,q-80,f-auto",
        })
        transformation = [v for k, v in body if k == "transformation"]
        assert len(transformation) == 1
        parsed = json.loads(transformation[0])
        assert parsed == {"pre": "w-1600,q-80,f-auto"}

    def test_payload_is_private_file_flag(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        body = a._build_optimize_payload({
            "source_url": "https://x.example.com/a.jpg",
            "file_name": "a.jpg",
            "is_private_file": True,
        })
        assert ("isPrivateFile", "true") in body

    def test_parse_response_non_dict_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        with patch.object(a, "_http_post", return_value="nope"):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_parse_response_missing_url_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        with patch.object(
            a, "_http_post",
            return_value={"message": "no upload happened"},
        ):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "no upload happened" in result.error.reason


# ── Optimize happy path ─────────────────────────────────────


class TestImageKitOptimize:
    def test_optimize_happy_path(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "fileId": "abc123",
                "name": "product-1_abc.jpg",
                "url": "https://ik.imagekit.io/demo/products/product-1_abc.jpg",
                "thumbnailUrl": (
                    "https://ik.imagekit.io/demo/products/product-1_thumb.jpg"
                ),
                "size": 48234,
                "width": 1600,
                "height": 900,
                "fileType": "image",
                "filePath": "/products/product-1_abc.jpg",
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )

        assert result.ok
        assert result.data["url"].startswith("https://ik.imagekit.io/")
        assert result.data["file_id"] == "abc123"
        assert result.data["size"] == 48234
        assert result.data["width"] == 1600
        assert result.data["height"] == 900
        assert result.data["file_type"] == "image"
        assert result.data["thumbnail_url"].endswith("product-1_thumb.jpg")
        assert result.cost_usd == pytest.approx(0.0)

        assert captured["url"].endswith("/api/v1/files/upload")
        assert (
            "file", "https://cdn.shop.example.com/img/product-1.jpg",
        ) in captured["body"]
        assert ("fileName", "product-1.jpg") in captured["body"]
        assert captured["headers"]["Authorization"].startswith("Basic ")

    def test_optimize_auth_error_mapped(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad private key"),
        ):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_optimize_rate_limit_mapped(self, monkeypatch):
        from core.adapters.image_cdn.imagekit import ImageKitAdapter
        _configure_imagekit(monkeypatch)
        a = ImageKitAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── Bootstrap ───────────────────────────────────────────────


class TestImageCdnBootstrap:
    def test_register_all_adds_imagekit(self):
        from core.adapters.image_cdn.bootstrap import register_all
        status = register_all()
        assert "imagekit" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.image_cdn.bootstrap import register_all
        status = register_all()
        assert status["imagekit"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.image_cdn.bootstrap import register_all
        _configure_imagekit(monkeypatch)
        status = register_all()
        assert status["imagekit"] is True

    def test_register_all_idempotent(self):
        from core.adapters.image_cdn.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "imagekit"
        ]) == 1


# ── Smart router routing + metrics capture ─────────────────


class TestImageCdnRouterIntegration:
    def test_router_routes_optimize_image_to_imagekit(self, monkeypatch):
        from core.adapters.image_cdn.bootstrap import register_all
        _configure_imagekit(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.OPTIMIZE_IMAGE)
        assert chosen.name == "imagekit"

    def test_router_raises_when_imagekit_unconfigured(self):
        from core.adapters.image_cdn.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.OPTIMIZE_IMAGE)

    def test_end_to_end_optimize_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome."""
        from core.adapters.image_cdn.bootstrap import register_all
        from core.adapters.image_cdn.imagekit import ImageKitAdapter

        _configure_imagekit(monkeypatch)
        register_all()

        adapter = get_registry().get("imagekit")
        assert isinstance(adapter, ImageKitAdapter)

        def fake_post(url, body, headers):
            return {
                "fileId": "xyz",
                "name": "p1.jpg",
                "url": "https://ik.imagekit.io/demo/p1.jpg",
                "size": 12345,
                "width": 1024,
                "height": 768,
                "fileType": "image",
            }

        with patch.object(adapter, "_http_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )

        assert result.ok
        assert result.adapter == "imagekit"
        assert result.capability == "optimize_image"
        assert result.data["url"] == "https://ik.imagekit.io/demo/p1.jpg"
        assert result.cost_usd == pytest.approx(0.0)

        stats = get_metrics().stats_for("imagekit")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        from core.adapters.image_cdn.bootstrap import register_all
        from core.adapters.image_cdn.imagekit import ImageKitAdapter

        _configure_imagekit(monkeypatch)
        register_all()
        adapter = get_registry().get("imagekit")
        assert isinstance(adapter, ImageKitAdapter)

        with patch.object(
            adapter, "_http_post",
            side_effect=AdapterAuthError(adapter.name, "bad key"),
        ):
            result = get_router().execute(
                Capability.OPTIMIZE_IMAGE, dict(_VALID_OPTIMIZE),
            )

        assert not result.ok
        stats = get_metrics().stats_for("imagekit")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
