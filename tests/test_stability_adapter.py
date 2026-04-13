"""Tests for the Stability AI image adapter.

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
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


def _configure_stability(monkeypatch, *, key="sk-stab-test"):
    monkeypatch.setenv("STABILITY_API_KEY", key)
    get_config().reload()


class TestStabilityMetadata:
    def test_metadata(self):
        from core.adapters.image.stability import StabilityAdapter
        a = StabilityAdapter()
        assert a.name == "stability_ai"
        assert a.category == AdapterCategory.IMAGE_GEN
        assert Capability.GENERATE_IMAGE in a.capabilities
        assert Capability.OPTIMIZE_IMAGE in a.capabilities
        assert a.priority == 70

    def test_unconfigured_without_key(self):
        from core.adapters.image.stability import StabilityAdapter
        assert not StabilityAdapter().is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        assert StabilityAdapter().is_configured()


class TestStabilityGenerate:
    def test_generate_happy_path(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        raw = {"image": "base64encodedimage==", "seed": 42}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.GENERATE_IMAGE,
                {"prompt": "A product photo of running shoes"},
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["images"][0]["b64_json"] == "base64encodedimage=="
        assert result.data["seed"] == 42
        assert result.data["model"] == "sd3-large"

    def test_generate_requires_prompt(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        result = a.execute(Capability.GENERATE_IMAGE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_generate_with_negative_prompt(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        raw = {"image": "abc==", "seed": 1}

        with patch.object(a, "_http_post", return_value=raw) as mocked:
            a.execute(
                Capability.GENERATE_IMAGE,
                {
                    "prompt": "Product photo",
                    "negative_prompt": "blurry, low quality",
                },
            )

        body = mocked.call_args[0][1]
        assert body["negative_prompt"] == "blurry, low quality"


class TestStabilityOptimize:
    def test_upscale_happy_path(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        raw = {"image": "upscaled_base64=="}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE,
                {"action": "upscale", "image_base64": "original_b64=="},
            )

        assert result.ok
        assert result.data["action"] == "upscale"
        assert result.data["image_base64"] == "upscaled_base64=="

    def test_remove_background_happy_path(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        raw = {"image": "nobg_base64=="}

        with patch.object(a, "_http_post", return_value=raw):
            result = a.execute(
                Capability.OPTIMIZE_IMAGE,
                {"action": "remove_background", "image_base64": "orig=="},
            )

        assert result.ok
        assert result.data["action"] == "remove_background"
        assert result.data["has_result"] is True

    def test_optimize_requires_image(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {"action": "upscale"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unsupported_optimize_action(self, monkeypatch):
        from core.adapters.image.stability import StabilityAdapter
        _configure_stability(monkeypatch)
        a = StabilityAdapter()

        result = a.execute(
            Capability.OPTIMIZE_IMAGE,
            {"action": "rotate", "image_base64": "x=="},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


class TestStabilityBootstrap:
    def test_register_all_includes_stability(self):
        from core.adapters.image.bootstrap import register_all
        status = register_all()
        assert "stability_ai" in status

    def test_router_prefers_dalle_for_generation(self, monkeypatch):
        """DALL-E 3 (80) > Stability (70) for GENERATE_IMAGE."""
        from core.adapters.image.bootstrap import register_all
        _configure_stability(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        get_config().reload()
        register_all()
        chain = get_router().candidates(Capability.GENERATE_IMAGE)
        names = [a.name for a in chain]
        assert names[0] == "dalle3"
        assert "stability_ai" in names
