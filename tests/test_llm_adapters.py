"""Tests for the 7 LLM adapters with mocked HTTP.

Real network calls are forbidden — every test patches
``LLMBaseAdapter._post_json`` (or, where the adapter overrides
``_call_vendor`` directly, the vendor method) to return a
canned response.

Coverage:

  * each adapter's class metadata (name, capabilities, priority,
    cost, free-tier limit)
  * ``is_configured`` correctly reflects the env var
  * happy-path response → AdapterResult success
  * error mapping (401 → AdapterAuthError, 429 → AdapterRateLimited,
    5xx → AdapterUnavailable)
  * vendor-specific schema translation (Gemini, Ollama,
    HuggingFace)
  * bootstrap.register_all wires every adapter into the registry
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterAuthError,
    AdapterCategory,
    AdapterRateLimited,
    AdapterResult,
    AdapterUnavailable,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError, AdapterNotConfigured


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Wipe every singleton + env var between tests."""
    for var in (
        "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "HUGGINGFACE_API_KEY",
        "OLLAMA_BASE_URL",
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


# ── Helpers ────────────────────────────────────────────────


def _openai_style_response(text: str = "hello world") -> dict:
    return {
        "id": "test_response",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "model": "test-model",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


# ── Groq ───────────────────────────────────────────────────


class TestGroqAdapter:
    def test_metadata(self):
        from core.adapters.llm.groq import GroqAdapter
        a = GroqAdapter()
        assert a.name == "groq"
        assert a.category == AdapterCategory.LLM
        assert Capability.CHAT_COMPLETE in a.capabilities
        assert Capability.CODE_GENERATE in a.capabilities
        assert a.priority == 90
        assert a.cost_per_call == 0.0
        assert a.free_tier_daily_limit == 14_400

    def test_unconfigured_without_api_key(self):
        from core.adapters.llm.groq import GroqAdapter
        a = GroqAdapter()
        assert not a.is_configured()

    def test_configured_when_env_set(self, monkeypatch):
        from core.adapters.llm.groq import GroqAdapter
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        get_config().reload()
        a = GroqAdapter()
        assert a.is_configured()

    def test_chat_complete_happy_path(self, monkeypatch):
        from core.adapters.llm.groq import GroqAdapter
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        get_config().reload()

        a = GroqAdapter()
        with patch.object(
            a, "_post_json",
            return_value=_openai_style_response("hi from groq"),
        ) as mocked:
            result = a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hello"},
            )

        assert result.ok
        assert result.data["text"] == "hi from groq"
        assert result.tokens_in == 10
        assert result.tokens_out == 5
        # Verify the request hit the right URL
        call_url = mocked.call_args[0][0]
        assert "groq.com" in call_url
        assert "/chat/completions" in call_url
        # Auth header sent
        headers = mocked.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer gsk_test"

    def test_chat_with_system_prompt(self, monkeypatch):
        from core.adapters.llm.groq import GroqAdapter
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_config().reload()
        a = GroqAdapter()

        captured_payload = {}
        def fake_post(url, payload, **kw):
            captured_payload.update(payload)
            return _openai_style_response()

        with patch.object(a, "_post_json", side_effect=fake_post):
            a.execute(
                Capability.CHAT_COMPLETE,
                {"system": "You are helpful", "prompt": "hi"},
            )

        assert captured_payload["messages"][0]["role"] == "system"
        assert captured_payload["messages"][0]["content"] == "You are helpful"
        assert captured_payload["messages"][1]["role"] == "user"


# ── DeepSeek ───────────────────────────────────────────────


class TestDeepSeekAdapter:
    def test_metadata(self):
        from core.adapters.llm.deepseek import DeepSeekAdapter
        a = DeepSeekAdapter()
        assert a.name == "deepseek"
        assert Capability.CODE_GENERATE in a.capabilities
        assert a.model_default == "deepseek-chat"

    def test_chat_happy_path(self, monkeypatch):
        from core.adapters.llm.deepseek import DeepSeekAdapter
        monkeypatch.setenv("DEEPSEEK_API_KEY", "ds_test")
        get_config().reload()

        a = DeepSeekAdapter()
        with patch.object(
            a, "_post_json",
            return_value=_openai_style_response("rust code"),
        ) as mocked:
            result = a.execute(
                Capability.CODE_GENERATE,
                {"prompt": "Write a Rust hello world"},
            )

        assert result.ok
        assert result.data["text"] == "rust code"
        assert "deepseek.com" in mocked.call_args[0][0]


# ── Mistral ────────────────────────────────────────────────


class TestMistralAdapter:
    def test_metadata(self):
        from core.adapters.llm.mistral import MistralAdapter
        a = MistralAdapter()
        assert a.name == "mistral"
        assert a.is_pii_safe() is True
        # Mistral is the EU PII fallback — confirm router-side
        # logic considers it safe
        from core.adapters.router import SmartRouter
        assert SmartRouter._is_pii_safe(a) is True


# ── OpenRouter ─────────────────────────────────────────────


class TestOpenRouterAdapter:
    def test_metadata(self):
        from core.adapters.llm.openrouter import OpenRouterAdapter
        a = OpenRouterAdapter()
        assert a.name == "openrouter"
        # Low priority — only used as fallback
        assert a.priority == 40

    def test_extra_headers(self):
        from core.adapters.llm.openrouter import OpenRouterAdapter
        a = OpenRouterAdapter()
        h = a.extra_headers()
        assert "HTTP-Referer" in h
        assert "X-Title" in h


# ── Gemini ─────────────────────────────────────────────────


class TestGeminiAdapter:
    def test_metadata(self):
        from core.adapters.llm.gemini import GeminiAdapter
        a = GeminiAdapter()
        assert a.name == "gemini"
        assert Capability.LONG_CONTEXT in a.capabilities
        assert Capability.IMAGE_ANALYZE in a.capabilities
        assert a.model_default == "gemini-2.5-flash"
        assert a.free_tier_daily_limit == 1_500

    def test_unconfigured_without_api_key(self):
        from core.adapters.llm.gemini import GeminiAdapter
        a = GeminiAdapter()
        assert not a.is_configured()

    def test_chat_happy_path_translates_schema(self, monkeypatch):
        """Gemini speaks ``contents`` not ``messages``. Adapter
        must translate before sending."""
        from core.adapters.llm.gemini import GeminiAdapter
        monkeypatch.setenv("GEMINI_API_KEY", "gem_test")
        get_config().reload()

        a = GeminiAdapter()

        captured_payload = {}
        def fake_post(url, payload, **kw):
            captured_payload.update(payload)
            return {
                "candidates": [{
                    "content": {
                        "parts": [{"text": "hi from gemini"}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }],
                "usageMetadata": {
                    "promptTokenCount": 8,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 12,
                },
                "modelVersion": "gemini-2.5-flash-001",
            }

        with patch.object(a, "_post_json", side_effect=fake_post) as mocked:
            result = a.execute(
                Capability.CHAT_COMPLETE,
                {"system": "be terse", "prompt": "hello"},
            )

        assert result.ok
        assert result.data["text"] == "hi from gemini"
        assert result.tokens_in == 8
        assert result.tokens_out == 4

        # Translated schema should have ``contents`` and
        # ``systemInstruction``, NOT ``messages``
        assert "contents" in captured_payload
        assert "systemInstruction" in captured_payload
        assert captured_payload["contents"][0]["role"] == "user"
        # API key encoded in URL
        assert "key=gem_test" in mocked.call_args[0][0]

    def test_5xx_returns_unavailable(self, monkeypatch):
        from core.adapters.llm.gemini import GeminiAdapter
        from core.adapters.errors import AdapterUnavailable
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        get_config().reload()
        a = GeminiAdapter()

        # Simulate _post_json raising the typed error directly
        def fake_post(*args, **kwargs):
            raise AdapterUnavailable(a.name, "vendor 5xx (502): bad gateway")

        with patch.object(a, "_post_json", side_effect=fake_post):
            result = a.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})

        assert not result.ok
        assert isinstance(result.error, AdapterUnavailable)


# ── Ollama ─────────────────────────────────────────────────


class TestOllamaAdapter:
    def test_metadata(self):
        from core.adapters.llm.ollama import OllamaAdapter
        a = OllamaAdapter()
        assert a.name == "ollama_local"
        assert a.cost_per_call == 0.0
        assert a.is_pii_safe() is True

    def test_default_url(self):
        from core.adapters.llm.ollama import OllamaAdapter
        a = OllamaAdapter()
        assert a.base_url() == "http://localhost:11434"

    def test_custom_url_via_env(self, monkeypatch):
        from core.adapters.llm.ollama import OllamaAdapter
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu.local:11434")
        get_config().reload()
        a = OllamaAdapter()
        assert a.base_url() == "http://gpu.local:11434"

    def test_chat_happy_path_translates_schema(self):
        from core.adapters.llm.ollama import OllamaAdapter
        a = OllamaAdapter()

        # Ollama returns a different schema — single ``message``
        # dict + ``prompt_eval_count`` / ``eval_count`` for tokens
        ollama_response = {
            "model": "llama3.3:8b",
            "created_at": "2026-04-08T12:00:00Z",
            "message": {
                "role": "assistant",
                "content": "hi from ollama",
            },
            "done": True,
            "prompt_eval_count": 12,
            "eval_count": 7,
            "total_duration": 100_000_000,
        }

        with patch.object(a, "_post_json", return_value=ollama_response) as mocked:
            result = a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hello"},
            )

        assert result.ok
        assert result.data["text"] == "hi from ollama"
        assert result.tokens_in == 12
        assert result.tokens_out == 7
        # Should hit /api/chat
        assert "/api/chat" in mocked.call_args[0][0]
        # No API key — Ollama is local
        headers = mocked.call_args[1]["headers"]
        assert "Authorization" not in headers


# ── HuggingFace ────────────────────────────────────────────


class TestHuggingFaceAdapter:
    def test_metadata(self):
        from core.adapters.llm.huggingface import HuggingFaceAdapter
        a = HuggingFaceAdapter()
        assert a.name == "huggingface"
        assert Capability.EMBED_TEXT in a.capabilities
        assert a.model_default == "sentence-transformers/all-MiniLM-L6-v2"

    def test_unconfigured_without_api_key(self):
        from core.adapters.llm.huggingface import HuggingFaceAdapter
        a = HuggingFaceAdapter()
        assert not a.is_configured()

    def test_embed_text_returns_vector(self, monkeypatch):
        from core.adapters.llm.huggingface import HuggingFaceAdapter
        monkeypatch.setenv("HUGGINGFACE_API_KEY", "hf_test")
        get_config().reload()

        a = HuggingFaceAdapter()
        # HF embeddings endpoint returns a list of floats (or
        # list of lists for batch input)
        fake_vector = [[0.1, 0.2, 0.3, 0.4, 0.5]]

        with patch.object(a, "_post_json", return_value=fake_vector) as mocked:
            result = a.execute(
                Capability.EMBED_TEXT,
                {"text": "Hello world"},
            )

        assert result.ok
        assert result.data["embeddings"] == fake_vector
        assert result.data["dimensions"] == 5
        # Endpoint = /models/<model_id>
        assert "sentence-transformers" in mocked.call_args[0][0]


# ── Bootstrap ──────────────────────────────────────────────


class TestBootstrap:
    def test_register_all_adds_all_adapters(self):
        from core.adapters.llm.bootstrap import register_all
        status = register_all()
        # 9 LLM adapters (original 7 + openai + anthropic)
        assert len(status) == 9
        names = set(status.keys())
        assert names == {
            "groq", "gemini", "deepseek", "mistral",
            "ollama_local", "openrouter", "huggingface",
            "openai", "anthropic",
        }

    def test_register_all_idempotent(self):
        from core.adapters.llm.bootstrap import register_all
        register_all()
        # Second call must NOT raise (replace=True)
        register_all()
        assert len(get_registry()) == 9

    def test_unconfigured_adapters_still_register(self):
        """All 7 register even with no env vars; the router just
        skips them via is_configured."""
        from core.adapters.llm.bootstrap import register_all
        status = register_all()
        # ollama_local is "configured" because the URL has a default
        configured = {k for k, v in status.items() if v}
        assert "ollama_local" in configured
        # Cloud adapters with no API key are not configured
        assert "groq" not in configured

    def test_router_picks_groq_after_bootstrap(self, monkeypatch):
        from core.adapters.llm.bootstrap import register_all
        from core.adapters import get_router
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_config().reload()
        register_all()

        chosen = get_router().route(Capability.CHAT_COMPLETE)
        assert chosen.name == "groq"  # priority 90, configured

    def test_router_picks_gemini_for_long_context(self, monkeypatch):
        from core.adapters.llm.bootstrap import register_all
        from core.adapters import get_router
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_config().reload()
        register_all()

        # Only Gemini implements LONG_CONTEXT
        chosen = get_router().route(Capability.LONG_CONTEXT)
        assert chosen.name == "gemini"

    def test_router_picks_ollama_for_pii(self):
        """PII routing must pick the local adapter."""
        from core.adapters.llm.bootstrap import register_all
        from core.adapters import get_router, RouteContext
        register_all()
        chosen = get_router().route(
            Capability.CHAT_COMPLETE,
            RouteContext(contains_pii=True),
        )
        assert chosen.name == "ollama_local"


# ── Error mapping ──────────────────────────────────────────


class TestErrorMapping:
    def test_429_maps_to_rate_limited(self, monkeypatch):
        from core.adapters.llm.groq import GroqAdapter
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_config().reload()
        a = GroqAdapter()

        # Stub _handle_http_error path by simulating a 429 in
        # _post_json. Use the typed error directly.
        with patch.object(
            a, "_post_json",
            side_effect=AdapterRateLimited("groq", "rate limit", retry_after=5.0),
        ):
            result = a.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})

        assert not result.ok
        assert isinstance(result.error, AdapterRateLimited)
        assert result.error.retry_after == 5.0

    def test_401_maps_to_auth_error(self, monkeypatch):
        from core.adapters.llm.groq import GroqAdapter
        monkeypatch.setenv("GROQ_API_KEY", "k")
        get_config().reload()
        a = GroqAdapter()

        with patch.object(
            a, "_post_json",
            side_effect=AdapterAuthError("groq", "bad key"),
        ):
            result = a.execute(Capability.CHAT_COMPLETE, {"prompt": "x"})

        assert not result.ok
        assert isinstance(result.error, AdapterAuthError)

    def test_handle_http_error_classification(self):
        from core.adapters.llm.groq import GroqAdapter
        a = GroqAdapter()
        # 401
        err = a._handle_http_error(401, "unauthorized")
        assert isinstance(err, AdapterAuthError)
        # 429
        err = a._handle_http_error(429, "slow down", retry_after=10)
        assert isinstance(err, AdapterRateLimited)
        assert err.retry_after == 10
        # 500
        err = a._handle_http_error(500, "internal")
        assert isinstance(err, AdapterUnavailable)
        # 400 → generic
        err = a._handle_http_error(400, "bad request")
        assert isinstance(err, AdapterError)
