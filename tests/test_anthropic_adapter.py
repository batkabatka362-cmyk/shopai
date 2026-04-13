"""Tests for the Anthropic Claude adapter with mocked HTTP.

Coverage:

  * Adapter metadata (name, category, capabilities, priority)
  * is_configured reflects ANTHROPIC_API_KEY env var
  * Request payload translation (system as top-level, stop_sequences)
  * Happy-path chat → AdapterResult success with content blocks
  * Response parsing (content blocks → text, usage mapping)
  * Auth header uses x-api-key (NOT Bearer)
  * Token-based cost estimation
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
        "ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
        "HUGGINGFACE_API_KEY", "OLLAMA_BASE_URL", "OPENAI_API_KEY",
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


def _anthropic_response(text: str = "hello from claude") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": text},
        ],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 15,
            "output_tokens": 8,
        },
    }


class TestAnthropicMetadata:
    def test_metadata(self):
        from core.adapters.llm.anthropic import AnthropicAdapter
        a = AnthropicAdapter()
        assert a.name == "anthropic"
        assert a.category == AdapterCategory.LLM
        assert Capability.CHAT_COMPLETE in a.capabilities
        assert Capability.REASON_DEEP in a.capabilities
        assert Capability.CODE_GENERATE in a.capabilities
        assert Capability.LONG_CONTEXT in a.capabilities
        assert a.priority == 85
        assert a.model_default == "claude-sonnet-4-6"

    def test_no_free_tier(self):
        from core.adapters.llm.anthropic import AnthropicAdapter
        a = AnthropicAdapter()
        assert a.free_tier_daily_limit == 0


class TestAnthropicConfig:
    def test_unconfigured_without_key(self):
        from core.adapters.llm.anthropic import AnthropicAdapter
        a = AnthropicAdapter()
        assert not a.is_configured()

    def test_configured_with_key(self, monkeypatch):
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        get_config().reload()
        a = AnthropicAdapter()
        assert a.is_configured()


class TestAnthropicChat:
    def test_happy_path(self, monkeypatch):
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        get_config().reload()

        a = AnthropicAdapter()
        with patch.object(
            a, "_post_json",
            return_value=_anthropic_response("Claude says hi"),
        ) as mocked:
            result = a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hello"},
            )

        assert result.ok
        assert result.data["text"] == "Claude says hi"
        assert result.tokens_in == 15
        assert result.tokens_out == 8
        call_url = mocked.call_args[0][0]
        assert "api.anthropic.com" in call_url
        assert "/messages" in call_url

    def test_auth_header_uses_x_api_key(self, monkeypatch):
        """Anthropic uses x-api-key, NOT Bearer token."""
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
        get_config().reload()

        a = AnthropicAdapter()
        with patch.object(
            a, "_post_json",
            return_value=_anthropic_response(),
        ) as mocked:
            a.execute(Capability.CHAT_COMPLETE, {"prompt": "hi"})

        headers = mocked.call_args[1]["headers"]
        assert headers["x-api-key"] == "sk-ant-secret"
        assert "Authorization" not in headers
        assert "anthropic-version" in headers

    def test_system_as_top_level(self, monkeypatch):
        """System prompt is a top-level 'system' field, not a message."""
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        get_config().reload()
        a = AnthropicAdapter()

        captured = {}
        def fake_post(url, payload, **kw):
            captured.update(payload)
            return _anthropic_response()

        with patch.object(a, "_post_json", side_effect=fake_post):
            a.execute(
                Capability.CHAT_COMPLETE,
                {"system": "You are ShopAI", "prompt": "hi"},
            )

        # system is top-level, not in messages
        assert captured["system"] == "You are ShopAI"
        # messages should only have the user message
        assert len(captured["messages"]) == 1
        assert captured["messages"][0]["role"] == "user"

    def test_stop_sequences(self, monkeypatch):
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        get_config().reload()
        a = AnthropicAdapter()

        captured = {}
        def fake_post(url, payload, **kw):
            captured.update(payload)
            return _anthropic_response()

        with patch.object(a, "_post_json", side_effect=fake_post):
            a.execute(
                Capability.CHAT_COMPLETE,
                {"prompt": "hi", "stop": ["DONE", "END"]},
            )

        assert captured["stop_sequences"] == ["DONE", "END"]

    def test_multi_content_blocks(self, monkeypatch):
        """Response with multiple text content blocks gets concatenated."""
        from core.adapters.llm.anthropic import AnthropicAdapter
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        get_config().reload()
        a = AnthropicAdapter()

        multi_block_response = {
            "content": [
                {"type": "text", "text": "Part 1. "},
                {"type": "text", "text": "Part 2."},
            ],
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }

        with patch.object(a, "_post_json", return_value=multi_block_response):
            result = a.execute(Capability.CHAT_COMPLETE, {"prompt": "hi"})

        assert result.ok
        assert result.data["text"] == "Part 1. Part 2."


class TestAnthropicCost:
    def test_token_based_cost(self):
        from core.adapters.llm.anthropic import AnthropicAdapter
        a = AnthropicAdapter()
        cost = a._estimate_call_cost(tokens_in=1000, tokens_out=500)
        expected = 1000 * 3.00 / 1_000_000 + 500 * 15.00 / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_zero_tokens_zero_cost(self):
        from core.adapters.llm.anthropic import AnthropicAdapter
        a = AnthropicAdapter()
        assert a._estimate_call_cost(tokens_in=0, tokens_out=0) == 0.0
