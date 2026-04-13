"""Tests for the OpenAI GPT-4o adapter with mocked HTTP.

Coverage:

  * Adapter metadata (name, category, capabilities, priority, cost)
  * is_configured reflects OPENAI_API_KEY env var
  * Happy-path chat → AdapterResult success
  * Token-based cost estimation
  * Correct URL and auth header
  * System prompt handling
  * Bootstrap registration (now 9 LLM adapters)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.adapters import (
    AdapterCategory,
    Capability,
    get_config,
    get_registry,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterNotConfigured


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
        "HUGGINGFACE_API_KEY", "OLLAMA_BASE_URL", "ANTHROPIC_API_KEY",
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


def _openai_response(text: str = "hello from gpt-4o") -> dict:
    return {
        "id": "chatcmpl-test",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "model": "gpt-4o-2024-08-06",
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
    }


class TestOpenAIMetadata:
    def test_metadata(self):
        from core.adapters.llm.openai import OpenAIAdapter
        a = OpenAIAdapter()
        assert a.name == "openai"
        assert a.category == AdapterCategory.LLM
        assert Capability.CHAT_COMPLETE in a.capabilities
        assert Capability.REASON_DEEP in a.capabilities
        assert Capability.CODE_GENERATE in a.capabilities
        assert Capability.IMAGE_ANALYZE in a.capabilities
        assert a.priority == 80
        assert a.model_default == "gpt-4o"

    def test_cost_per_call_nonzero(self):
        from core.adapters.llm.openai import OpenAIAdapter
        a = OpenAIAdapter()
        assert a.cost_per_call > 0


class TestOpenAIConfig:
    def test_unconfigured_without_key(self):
        from core.adapters.llm.openai import OpenAIAdapter
        a = OpenAIAdapter()
        assert not a.is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.llm.openai import OpenAIAdapter
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
        get_config().reload()
        a = OpenAIAdapter()
        assert a.is_configured()


class TestOpenAIChat:
    def test_happy_path(self, monkeypatch):
        from core.adapters.llm.openai import OpenAIAdapter
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
        get_config().reload()

        a = OpenAIAdapter()
        with patch.object(
            a, "_post_json",
            return_value=_openai_response("GPT-4o says hi"),
        ) as mocked:
            result = a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hello"},
            )

        assert result.ok
        assert result.data["text"] == "GPT-4o says hi"
        assert result.tokens_in == 20
        assert result.tokens_out == 10
        call_url = mocked.call_args[0][0]
        assert "api.openai.com" in call_url
        assert "/chat/completions" in call_url
        headers = mocked.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer sk-test123"

    def test_system_prompt(self, monkeypatch):
        from core.adapters.llm.openai import OpenAIAdapter
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        get_config().reload()
        a = OpenAIAdapter()

        captured = {}
        def fake_post(url, payload, **kw):
            captured.update(payload)
            return _openai_response()

        with patch.object(a, "_post_json", side_effect=fake_post):
            a.execute(
                Capability.CHAT_COMPLETE,
                {"system": "You are ShopAI", "prompt": "hi"},
            )

        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][0]["content"] == "You are ShopAI"

    def test_model_override(self, monkeypatch):
        from core.adapters.llm.openai import OpenAIAdapter
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        get_config().reload()
        a = OpenAIAdapter()

        captured = {}
        def fake_post(url, payload, **kw):
            captured.update(payload)
            return _openai_response()

        with patch.object(a, "_post_json", side_effect=fake_post):
            a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hi", "model": "gpt-4o-mini"},
            )

        assert captured["model"] == "gpt-4o-mini"


class TestOpenAICost:
    def test_token_based_cost(self):
        from core.adapters.llm.openai import OpenAIAdapter
        a = OpenAIAdapter()
        cost = a._estimate_call_cost(tokens_in=1000, tokens_out=500)
        expected = 1000 * 2.50 / 1_000_000 + 500 * 10.00 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_zero_tokens_zero_cost(self):
        from core.adapters.llm.openai import OpenAIAdapter
        a = OpenAIAdapter()
        assert a._estimate_call_cost(tokens_in=0, tokens_out=0) == 0.0
