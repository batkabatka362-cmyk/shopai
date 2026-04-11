"""Regression tests for the image-generation adapter family.

Wave 1 #3 — DALL-E 3 only.

Real HTTP calls are forbidden — every test patches the adapter's
``_http_post`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes GENERATE_IMAGE
  * ImageBaseAdapter validates inputs (prompt required / length;
    n bounds) and rejects unknown capabilities
  * DallE3Adapter
        - registry metadata (name, category, capabilities,
          priority, cost)
        - is_configured() requires OPENAI_API_KEY
        - _generate_url points at /v1/images/generations
        - _auth_headers use Bearer
        - payload forwards size / quality / style / response_format
        - payload pins n=1 regardless of caller input (DALL-E 3
          only accepts n=1)
        - happy path: url + revised_prompt captured
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes GENERATE_IMAGE to dalle3 when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome (Wave 1 success criterion: a new
          external system is reachable through the router and the
          metrics layer records the call, INCLUDING cost_usd)
"""
from __future__ import annotations

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
    """Clear image-adapter env + every singleton between tests."""
    for var in (
        "OPENAI_API_KEY",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "PAYPAL_CLIENT_ID",
        "PAYPAL_CLIENT_SECRET",
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


def _configure_openai(monkeypatch) -> None:
    """Set OPENAI_API_KEY + reload the config singleton."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-xxxxxxxx")
    get_config().reload()


_VALID_PROMPT = {
    "prompt": "A watercolour hero banner of autumn leaves",
    "size": "1024x1024",
    "quality": "standard",
    "style": "vivid",
}


# ── Capability enum ─────────────────────────────────────────


class TestImageCapabilities:
    def test_generate_image_capability_exists(self):
        assert Capability("generate_image") is Capability.GENERATE_IMAGE


# ── ImageBaseAdapter validation ─────────────────────────────


class TestImageBaseAdapter:
    def test_prompt_is_required(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        result = a.execute(Capability.GENERATE_IMAGE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "prompt" in result.error.reason

    def test_prompt_too_long_rejected(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        result = a.execute(
            Capability.GENERATE_IMAGE,
            {"prompt": "x" * 4_001},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "too long" in result.error.reason

    def test_n_out_of_range_rejected(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        result = a.execute(
            Capability.GENERATE_IMAGE,
            {"prompt": "hi", "n": 99},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_n_non_integer_rejected(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        result = a.execute(
            Capability.GENERATE_IMAGE,
            {"prompt": "hi", "n": "not-a-number"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        # SEND_EMAIL_TRANSACTIONAL is a real Capability but not
        # one DALL-E 3 implements.
        result = a.execute(
            Capability.SEND_EMAIL_TRANSACTIONAL, {},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── DallE3Adapter ───────────────────────────────────────────


class TestDallE3Adapter:
    def test_metadata(self):
        from core.adapters.image.dalle3 import DallE3Adapter
        a = DallE3Adapter()
        assert a.name == "dalle3"
        assert a.category == AdapterCategory.IMAGE_GEN
        assert Capability.GENERATE_IMAGE in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.04
        assert a.model_default == "dall-e-3"

    def test_unconfigured_without_key(self):
        from core.adapters.image.dalle3 import DallE3Adapter
        assert not DallE3Adapter().is_configured()

    def test_configured_with_api_key(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        assert DallE3Adapter().is_configured()

    def test_generate_url(self):
        from core.adapters.image.dalle3 import DallE3Adapter
        a = DallE3Adapter()
        assert a._generate_url() == (
            "https://api.openai.com/v1/images/generations"
        )

    def test_auth_headers_use_bearer(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == "Bearer sk-test-xxxxxxxx"
        assert headers["Content-Type"] == "application/json"

    def test_payload_forwards_known_fields(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        body = a._build_generate_payload({
            "prompt": "test prompt",
            "size": "1024x1792",
            "quality": "hd",
            "style": "natural",
            "response_format": "url",
            "user": "shopai-cycle-42",
        })
        assert body["model"] == "dall-e-3"
        assert body["prompt"] == "test prompt"
        assert body["n"] == 1
        assert body["size"] == "1024x1792"
        assert body["quality"] == "hd"
        assert body["style"] == "natural"
        assert body["response_format"] == "url"
        assert body["user"] == "shopai-cycle-42"

    def test_payload_pins_n_to_one(self, monkeypatch):
        """DALL-E 3 only supports n=1. The adapter must NOT forward
        a caller-supplied n > 1 or OpenAI returns HTTP 400."""
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        # Validation allows n up to 10, but DALL-E 3 overrides it.
        body = a._build_generate_payload({
            "prompt": "hi", "n": 5,
        })
        assert body["n"] == 1

    def test_payload_drops_unknown_quality(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        body = a._build_generate_payload({
            "prompt": "hi", "quality": "ultra",
        })
        # "ultra" isn't a valid DALL-E 3 quality; should be dropped.
        assert "quality" not in body


# ── Generate happy path ─────────────────────────────────────


class TestDallE3Generate:
    def test_generate_happy_path(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "created": 1_700_000_000,
                "data": [{
                    "url": "https://cdn.openai.com/img/abc.png",
                    "revised_prompt": "A detailed watercolour...",
                }],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )

        assert result.ok
        assert result.data["count"] == 1
        assert result.data["images"][0]["url"] == (
            "https://cdn.openai.com/img/abc.png"
        )
        assert result.data["images"][0]["revised_prompt"] == (
            "A detailed watercolour..."
        )
        assert result.data["model"] == "dall-e-3"
        assert result.cost_usd == 0.04
        assert result.model == "dall-e-3"

        assert captured["url"].endswith("/v1/images/generations")
        assert captured["body"]["prompt"] == _VALID_PROMPT["prompt"]
        assert captured["body"]["size"] == "1024x1024"
        assert captured["headers"]["Authorization"] == (
            "Bearer sk-test-xxxxxxxx"
        )

    def test_generate_b64_response_format(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()

        def fake_post(url, body, headers):
            assert body["response_format"] == "b64_json"
            return {
                "data": [{
                    "b64_json": "iVBORw0KGgo=",
                    "revised_prompt": "...",
                }],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.GENERATE_IMAGE,
                {
                    "prompt": "hi",
                    "response_format": "b64_json",
                },
            )

        assert result.ok
        assert result.data["images"][0]["b64_json"] == "iVBORw0KGgo="
        assert result.data["images"][0]["url"] == ""

    def test_generate_auth_error_mapped(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad key"),
        ):
            result = a.execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_generate_rate_limit_mapped(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "too many"),
        ):
            result = a.execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)

    def test_generate_non_dict_response_raises(self, monkeypatch):
        from core.adapters.image.dalle3 import DallE3Adapter
        from core.adapters.errors import AdapterError
        _configure_openai(monkeypatch)
        a = DallE3Adapter()
        with patch.object(a, "_http_post", return_value=[1, 2, 3]):
            result = a.execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)


# ── Cost estimation ─────────────────────────────────────────


class TestDallE3CostEstimate:
    def test_estimate_cost_default(self):
        from core.adapters.image.dalle3 import DallE3Adapter
        a = DallE3Adapter()
        assert a.estimate_cost(
            Capability.GENERATE_IMAGE, {"prompt": "hi"},
        ) == 0.04

    def test_estimate_cost_scales_with_n(self):
        from core.adapters.image.dalle3 import DallE3Adapter
        a = DallE3Adapter()
        # estimate_cost is budget-planning only; DALL-E 3 forces
        # n=1 at request time, but the estimate uses the caller's
        # number so budget-aware routers stay conservative.
        assert a.estimate_cost(
            Capability.GENERATE_IMAGE, {"prompt": "hi", "n": 3},
        ) == pytest.approx(0.12)


# ── Bootstrap ───────────────────────────────────────────────


class TestImageBootstrap:
    def test_register_all_adds_dalle3(self):
        from core.adapters.image.bootstrap import register_all
        status = register_all()
        assert "dalle3" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.image.bootstrap import register_all
        status = register_all()
        assert status["dalle3"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.image.bootstrap import register_all
        _configure_openai(monkeypatch)
        status = register_all()
        assert status["dalle3"] is True

    def test_register_all_idempotent(self):
        from core.adapters.image.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "dalle3"
        ]) == 1


# ── Smart router routing + metrics capture ──────────────────


class TestImageRouterIntegration:
    def test_router_routes_generate_image_to_dalle3(self, monkeypatch):
        from core.adapters.image.bootstrap import register_all
        _configure_openai(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.GENERATE_IMAGE)
        assert chosen.name == "dalle3"

    def test_router_raises_when_dalle3_unconfigured(self):
        from core.adapters.image.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.GENERATE_IMAGE)

    def test_end_to_end_generate_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome,
        INCLUDING cost_usd so the brain's budget advisor can see
        image-gen spend separately from LLM spend."""
        from core.adapters.image.bootstrap import register_all
        from core.adapters.image.dalle3 import DallE3Adapter

        _configure_openai(monkeypatch)
        register_all()

        adapter = get_registry().get("dalle3")
        assert isinstance(adapter, DallE3Adapter)

        def fake_post(url, body, headers):
            return {
                "data": [{
                    "url": "https://cdn.openai.com/img/x.png",
                    "revised_prompt": "rewritten",
                }],
            }

        with patch.object(adapter, "_http_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )

        assert result.ok
        assert result.adapter == "dalle3"
        assert result.capability == "generate_image"
        assert result.data["images"][0]["url"] == (
            "https://cdn.openai.com/img/x.png"
        )
        assert result.cost_usd == 0.04

        stats = get_metrics().stats_for("dalle3")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        """A failed call must still flow into the metrics layer so
        the router's success-rate EMA degrades."""
        from core.adapters.image.bootstrap import register_all
        from core.adapters.image.dalle3 import DallE3Adapter

        _configure_openai(monkeypatch)
        register_all()
        adapter = get_registry().get("dalle3")
        assert isinstance(adapter, DallE3Adapter)

        with patch.object(
            adapter, "_http_post",
            side_effect=AdapterAuthError(adapter.name, "bad key"),
        ):
            result = get_router().execute(
                Capability.GENERATE_IMAGE, dict(_VALID_PROMPT),
            )

        assert not result.ok
        stats = get_metrics().stats_for("dalle3")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
