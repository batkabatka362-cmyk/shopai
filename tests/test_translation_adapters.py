"""Regression tests for the translation adapter family.

Wave 1 extension — DeepL only.

Real HTTP calls are forbidden — every test patches the
adapter's ``_http_post`` helper so the suite stays hermetic.

Coverage matrix:

  * Capability enum exposes TRANSLATE_TEXT
  * TranslationBaseAdapter validates inputs (text required +
    non-empty, max length, batch size, target_lang length,
    source_lang optional) and rejects unknown capabilities
  * DeepLAdapter
        - registry metadata (name, category, capabilities,
          priority, cost_per_char)
        - is_configured() requires DEEPL_API_KEY
        - base_url auto-picks free vs paid host based on ":fx"
          suffix
        - _translate_url points at /v2/translate
        - _auth_headers use DeepL-Auth-Key + form Content-Type
        - payload: repeated text key, upper-cased target_lang,
          optional source_lang, formality filtering
        - parse translations[] + detected_source_language
        - happy path captures translations + cost_per_char
        - HTTP 456 maps to AdapterQuotaExhausted
        - HTTP error mapping (auth, rate limit)
  * Bootstrap
        - register_all adds the adapter, idempotent
        - status map reflects is_configured
  * SmartRouter
        - routes TRANSLATE_TEXT to deepl when configured
        - raises NoAdapterAvailable when unconfigured
        - end-to-end execute() succeeds and the metrics collector
          captures the outcome INCLUDING cost_usd scaled by
          character count
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterQuotaExhausted,
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
    """Clear DeepL env + every adapter singleton between tests."""
    for var in (
        "DEEPL_API_KEY",
        "FIRECRAWL_API_KEY",
        "BREVO_API_KEY",
        "RESEND_API_KEY",
        "OPENAI_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
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


def _configure_deepl(monkeypatch, *, free: bool = False) -> str:
    """Set a DeepL key; free-tier keys end in ':fx'."""
    key = "test-deepl-key-xxxxxxxx"
    if free:
        key += ":fx"
    monkeypatch.setenv("DEEPL_API_KEY", key)
    get_config().reload()
    return key


_VALID_TRANSLATE = {
    "text": "Your order has shipped.",
    "target_lang": "de",
    "source_lang": "en",
}


# ── Capability enum ─────────────────────────────────────────


class TestTranslationCapabilities:
    def test_translate_text_capability_exists(self):
        assert Capability("translate_text") is Capability.TRANSLATE_TEXT


# ── TranslationBaseAdapter validation ───────────────────────


class TestTranslationBaseValidation:
    def test_text_is_required(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(Capability.TRANSLATE_TEXT, {"target_lang": "de"})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "text" in result.error.reason

    def test_text_must_be_non_empty(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": "   ", "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_text_too_long_rejected(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": "x" * 50_001, "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "too long" in result.error.reason.lower()

    def test_text_list_must_be_non_empty(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": [], "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_text_list_batch_too_large_rejected(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": ["hi"] * 51, "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "batch" in result.error.reason.lower()

    def test_text_list_segment_must_be_string(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": ["ok", 123], "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_text_wrong_type_rejected(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": 42, "target_lang": "de"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_target_lang_required(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT, {"text": "hi"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "target_lang" in result.error.reason

    def test_target_lang_length_check(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": "hi", "target_lang": "x"},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_regional_target_lang_accepted(self, monkeypatch):
        """EN-GB / PT-BR style codes must pass validation."""
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()

        def fake_post(url, body, headers):
            return {
                "translations": [
                    {"text": "Hello", "detected_source_language": "FR"},
                ],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.TRANSLATE_TEXT,
                {"text": "Bonjour", "target_lang": "en-GB"},
            )
        assert result.ok

    def test_source_lang_wrong_type_rejected(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(
            Capability.TRANSLATE_TEXT,
            {"text": "hi", "target_lang": "de", "source_lang": 12},
        )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_unknown_capability_returns_validation_error(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        result = a.execute(Capability.SEND_EMAIL_TRANSACTIONAL, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)


# ── DeepLAdapter ────────────────────────────────────────────


class TestDeepLAdapter:
    def test_metadata(self):
        from core.adapters.translation.deepl import DeepLAdapter
        a = DeepLAdapter()
        assert a.name == "deepl"
        assert a.category == AdapterCategory.TRANSLATION
        assert Capability.TRANSLATE_TEXT in a.capabilities
        assert a.priority == 80
        assert a.cost_per_char == pytest.approx(0.000025)
        assert a.cost_per_call == 0.0

    def test_unconfigured_without_key(self):
        from core.adapters.translation.deepl import DeepLAdapter
        assert not DeepLAdapter().is_configured()

    def test_configured_with_api_key(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        assert DeepLAdapter().is_configured()

    def test_base_url_paid_by_default(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch, free=False)
        a = DeepLAdapter()
        assert a.base_url == "https://api.deepl.com"

    def test_base_url_free_for_fx_suffix(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch, free=True)
        a = DeepLAdapter()
        assert a.base_url == "https://api-free.deepl.com"

    def test_base_url_falls_back_when_unconfigured(self):
        from core.adapters.translation.deepl import DeepLAdapter
        a = DeepLAdapter()
        # Even without a key, base_url should return a usable host.
        assert a.base_url == "https://api.deepl.com"

    def test_translate_url_paid(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch, free=False)
        a = DeepLAdapter()
        assert a._translate_url() == "https://api.deepl.com/v2/translate"

    def test_translate_url_free(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch, free=True)
        a = DeepLAdapter()
        assert a._translate_url() == (
            "https://api-free.deepl.com/v2/translate"
        )

    def test_auth_headers_use_deepl_auth_key(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        key = _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        headers = a._auth_headers()
        assert headers["Authorization"] == f"DeepL-Auth-Key {key}"
        assert headers["Content-Type"] == (
            "application/x-www-form-urlencoded"
        )
        assert headers["Accept"] == "application/json"

    def test_payload_single_string(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(dict(_VALID_TRANSLATE))
        assert ("text", "Your order has shipped.") in body
        assert ("target_lang", "DE") in body
        assert ("source_lang", "EN") in body

    def test_payload_list_batch_repeats_text_key(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {
                "text": ["Line A", "Line B", "Line C"],
                "target_lang": "fr",
            },
        )
        text_values = [v for k, v in body if k == "text"]
        assert text_values == ["Line A", "Line B", "Line C"]
        assert ("target_lang", "FR") in body

    def test_payload_uppercases_target_lang(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {"text": "hi", "target_lang": "en-gb"},
        )
        assert ("target_lang", "EN-GB") in body

    def test_payload_skips_source_lang_when_missing(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {"text": "hi", "target_lang": "de"},
        )
        assert not any(k == "source_lang" for k, _ in body)

    def test_payload_valid_formality_included(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {"text": "hi", "target_lang": "de", "formality": "more"},
        )
        assert ("formality", "more") in body

    def test_payload_invalid_formality_dropped(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {"text": "hi", "target_lang": "de", "formality": "shouty"},
        )
        assert not any(k == "formality" for k, _ in body)

    def test_payload_preserve_formatting_flag(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        body = a._build_translate_payload(
            {
                "text": "hi", "target_lang": "de",
                "preserve_formatting": True,
            },
        )
        assert ("preserve_formatting", "1") in body

    def test_parse_response_non_dict_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        with patch.object(a, "_http_post", return_value="not-a-dict"):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)

    def test_parse_response_missing_translations_raises(self, monkeypatch):
        from core.adapters.errors import AdapterError
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        with patch.object(a, "_http_post", return_value={"foo": "bar"}):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)


# ── Translate happy path ───────────────────────────────────


class TestDeepLTranslate:
    def test_translate_happy_path(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()

        captured = {}

        def fake_post(url, body, headers):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            return {
                "translations": [
                    {
                        "text": "Ihre Bestellung wurde versandt.",
                        "detected_source_language": "EN",
                    },
                ],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )

        assert result.ok
        assert result.data["target_lang"] == "de"
        assert len(result.data["translations"]) == 1
        assert result.data["translations"][0]["text"] == (
            "Ihre Bestellung wurde versandt."
        )
        assert result.data["translations"][0]["detected_source"] == "en"
        # cost = chars * 0.000025
        expected_chars = len(_VALID_TRANSLATE["text"])
        assert result.data["characters"] == expected_chars
        assert result.cost_usd == pytest.approx(
            expected_chars * 0.000025,
        )

        assert captured["url"].endswith("/v2/translate")
        assert ("text", "Your order has shipped.") in captured["body"]
        assert ("target_lang", "DE") in captured["body"]
        assert captured["headers"]["Authorization"].startswith(
            "DeepL-Auth-Key ",
        )

    def test_translate_batch_happy_path(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()

        def fake_post(url, body, headers):
            return {
                "translations": [
                    {"text": "Hallo", "detected_source_language": "EN"},
                    {"text": "Welt", "detected_source_language": "EN"},
                ],
            }

        with patch.object(a, "_http_post", side_effect=fake_post):
            result = a.execute(
                Capability.TRANSLATE_TEXT,
                {
                    "text": ["Hello", "World"],
                    "target_lang": "de",
                },
            )
        assert result.ok
        assert len(result.data["translations"]) == 2
        # chars = len("Hello") + len("World") = 10
        assert result.data["characters"] == 10
        assert result.cost_usd == pytest.approx(10 * 0.000025)

    def test_translate_quota_exhausted_mapped(self, monkeypatch):
        """DeepL HTTP 456 → AdapterQuotaExhausted so the router
        can fall back to another translator."""
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterQuotaExhausted(a.name, "out of chars"),
        ):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterQuotaExhausted)

    def test_translate_auth_error_mapped(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterAuthError(a.name, "bad key"),
        ):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_translate_rate_limit_mapped(self, monkeypatch):
        from core.adapters.translation.deepl import DeepLAdapter
        _configure_deepl(monkeypatch)
        a = DeepLAdapter()
        with patch.object(
            a, "_http_post",
            side_effect=AdapterRateLimited(a.name, "throttled"),
        ):
            result = a.execute(
                Capability.TRANSLATE_TEXT, dict(_VALID_TRANSLATE),
            )
        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)


# ── Bootstrap ───────────────────────────────────────────────


class TestTranslationBootstrap:
    def test_register_all_adds_deepl(self):
        from core.adapters.translation.bootstrap import register_all
        status = register_all()
        assert "deepl" in status

    def test_register_all_unconfigured_without_env(self):
        from core.adapters.translation.bootstrap import register_all
        status = register_all()
        assert status["deepl"] is False

    def test_register_all_configured_when_env_set(self, monkeypatch):
        from core.adapters.translation.bootstrap import register_all
        _configure_deepl(monkeypatch)
        status = register_all()
        assert status["deepl"] is True

    def test_register_all_idempotent(self):
        from core.adapters.translation.bootstrap import register_all
        register_all()
        register_all()
        assert len([
            n for n in get_registry().names() if n == "deepl"
        ]) == 1


# ── Smart router routing + metrics capture ─────────────────


class TestTranslationRouterIntegration:
    def test_router_routes_translate_text_to_deepl(self, monkeypatch):
        from core.adapters.translation.bootstrap import register_all
        _configure_deepl(monkeypatch)
        register_all()
        chosen = get_router().route(Capability.TRANSLATE_TEXT)
        assert chosen.name == "deepl"

    def test_router_raises_when_deepl_unconfigured(self):
        from core.adapters.translation.bootstrap import register_all
        register_all()
        with pytest.raises(NoAdapterAvailable):
            get_router().route(Capability.TRANSLATE_TEXT)

    def test_end_to_end_translate_records_metrics(self, monkeypatch):
        """Wave 1 success criterion — the router reaches a brand-new
        external system AND MetricsCollector captures the outcome,
        INCLUDING cost_usd scaled by character count so translation
        spend shows up separately in the budget advisor."""
        from core.adapters.translation.bootstrap import register_all
        from core.adapters.translation.deepl import DeepLAdapter

        _configure_deepl(monkeypatch)
        register_all()

        adapter = get_registry().get("deepl")
        assert isinstance(adapter, DeepLAdapter)

        def fake_post(url, body, headers):
            return {
                "translations": [
                    {
                        "text": "Hallo Welt",
                        "detected_source_language": "EN",
                    },
                ],
            }

        with patch.object(adapter, "_http_post", side_effect=fake_post):
            result = get_router().execute(
                Capability.TRANSLATE_TEXT,
                {"text": "Hello world", "target_lang": "de"},
            )

        assert result.ok
        assert result.adapter == "deepl"
        assert result.capability == "translate_text"
        assert result.data["translations"][0]["text"] == "Hallo Welt"
        # "Hello world" = 11 chars → 11 * 0.000025
        assert result.cost_usd == pytest.approx(11 * 0.000025)

        stats = get_metrics().stats_for("deepl")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_success"] == 1
        assert stats["calls_failure"] == 0
        assert stats["success_rate"] == 1.0

    def test_router_records_failure_metric(self, monkeypatch):
        from core.adapters.translation.bootstrap import register_all
        from core.adapters.translation.deepl import DeepLAdapter

        _configure_deepl(monkeypatch)
        register_all()
        adapter = get_registry().get("deepl")
        assert isinstance(adapter, DeepLAdapter)

        with patch.object(
            adapter, "_http_post",
            side_effect=AdapterQuotaExhausted(
                adapter.name, "monthly quota exhausted",
            ),
        ):
            result = get_router().execute(
                Capability.TRANSLATE_TEXT,
                {"text": "Hello", "target_lang": "de"},
            )

        assert not result.ok
        stats = get_metrics().stats_for("deepl")
        assert stats is not None
        assert stats["calls_total"] == 1
        assert stats["calls_failure"] == 1
        assert stats["calls_success"] == 0
