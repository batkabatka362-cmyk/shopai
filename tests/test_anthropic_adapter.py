"""Tests for AnthropicAdapter -- W963-105."""
from __future__ import annotations

from unittest.mock import patch

from core.adapters.base import Capability
from core.adapters.errors import AdapterNotConfigured
from core.adapters.llm.anthropic import (
    _ANTHROPIC_VERSION,
    AnthropicAdapter,
)


# ── Configuration ─────────────────────────────────────────


class TestAnthropicConfiguration:
    def test_is_configured_returns_false_without_key(self):
        with patch(
            "core.adapters.llm.anthropic.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            adapter = AnthropicAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_returns_true_with_key(self):
        with patch(
            "core.adapters.llm.anthropic.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "sk-ant-test"
            adapter = AnthropicAdapter()
            assert adapter.is_configured() is True

    def test_api_key_raises_when_unset(self):
        with patch(
            "core.adapters.llm.anthropic.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            mock_cfg.return_value.env_var_for.return_value = (
                "ANTHROPIC_API_KEY"
            )
            adapter = AnthropicAdapter()
            try:
                adapter._api_key()
                raise AssertionError("expected raise")
            except AdapterNotConfigured as exc:
                assert "ANTHROPIC_API_KEY" in str(exc)


# ── Metadata ───────────────────────────────────────────────


class TestAnthropicMetadata:
    def test_name(self):
        assert AnthropicAdapter.name == "anthropic"

    def test_base_url_is_anthropic(self):
        adapter = AnthropicAdapter()
        assert "api.anthropic.com" in adapter.base_url

    def test_default_model_is_sonnet(self):
        adapter = AnthropicAdapter()
        assert "sonnet" in adapter.model_default.lower()

    def test_capabilities_include_reasoning(self):
        caps = AnthropicAdapter.capabilities
        assert Capability.CHAT_COMPLETE in caps
        assert Capability.REASON_DEEP in caps
        assert Capability.LONG_CONTEXT in caps
        assert Capability.CODE_GENERATE in caps

    def test_priority_below_openai(self):
        """OpenAI default for chat; Anthropic specialty for
        REASON_DEEP via router capability ranking."""
        from core.adapters.llm.openai import OpenAIAdapter
        assert (
            AnthropicAdapter.priority < OpenAIAdapter.priority
        )


# ── Request payload translation ────────────────────────────


class TestAnthropicPayload:
    def test_system_messages_hoisted_to_top_level_field(self):
        """OpenAI-style messages put system in messages[0];
        Anthropic wants it as a top-level ``system`` field."""
        adapter = AnthropicAdapter()
        messages = [
            {"role": "system", "content": "you are an empire ops AI"},
            {"role": "user", "content": "give me 3 actions"},
        ]
        payload = adapter._build_request_payload(
            messages=messages,
            model="claude-sonnet-4-5",
            max_tokens=512,
            temperature=0.7,
            stop=None,
            extra={},
        )
        # System hoisted, NOT in messages
        assert payload["system"] == "you are an empire ops AI"
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    def test_multiple_system_messages_concatenated(self):
        adapter = AnthropicAdapter()
        messages = [
            {"role": "system", "content": "first system"},
            {"role": "system", "content": "second system"},
            {"role": "user", "content": "hi"},
        ]
        payload = adapter._build_request_payload(
            messages=messages,
            model="claude-sonnet-4-5",
            max_tokens=100,
            temperature=0.5,
            stop=None,
            extra={},
        )
        assert "first system" in payload["system"]
        assert "second system" in payload["system"]

    def test_max_tokens_always_set(self):
        """Anthropic requires max_tokens. Base passes it
        through always."""
        adapter = AnthropicAdapter()
        payload = adapter._build_request_payload(
            messages=[{"role": "user", "content": "x"}],
            model="claude-sonnet-4-5",
            max_tokens=2048,
            temperature=0.7,
            stop=None,
            extra={},
        )
        assert payload["max_tokens"] == 2048

    def test_stop_sequences_renamed(self):
        """OpenAI uses 'stop'; Anthropic uses
        'stop_sequences'."""
        adapter = AnthropicAdapter()
        payload = adapter._build_request_payload(
            messages=[{"role": "user", "content": "x"}],
            model="claude-sonnet-4-5",
            max_tokens=100,
            temperature=0.7,
            stop=["</answer>"],
            extra={},
        )
        assert "stop" not in payload
        assert payload["stop_sequences"] == ["</answer>"]

    def test_stop_string_wrapped_in_list(self):
        adapter = AnthropicAdapter()
        payload = adapter._build_request_payload(
            messages=[{"role": "user", "content": "x"}],
            model="claude-sonnet-4-5",
            max_tokens=100,
            temperature=0.7,
            stop="END",
            extra={},
        )
        assert payload["stop_sequences"] == ["END"]


# ── Response parsing ───────────────────────────────────────


class TestAnthropicResponseParsing:
    def test_text_extraction_from_content_array(self):
        adapter = AnthropicAdapter()
        raw = {
            "content": [
                {"type": "text", "text": "Hello world"},
            ],
            "model": "claude-sonnet-4-5",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        text, usage, model = adapter._parse_response(raw)
        assert text == "Hello world"
        assert model == "claude-sonnet-4-5"

    def test_multi_part_content_concatenated(self):
        adapter = AnthropicAdapter()
        raw = {
            "content": [
                {"type": "text", "text": "First "},
                {"type": "text", "text": "Second"},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }
        text, usage, model = adapter._parse_response(raw)
        assert text == "First Second"

    def test_non_text_parts_skipped(self):
        """Tool use parts (type != text) silently dropped --
        text-only consumers don't need them."""
        adapter = AnthropicAdapter()
        raw = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "tool_use", "name": "x"},
                {"type": "text", "text": " world"},
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        text, _, _ = adapter._parse_response(raw)
        assert text == "Hello world"

    def test_usage_mapped_to_openai_names(self):
        """input_tokens -> prompt_tokens,
        output_tokens -> completion_tokens (matches what the
        base layer expects from every adapter)."""
        adapter = AnthropicAdapter()
        raw = {
            "content": [{"type": "text", "text": "x"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        _, usage, _ = adapter._parse_response(raw)
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 50
        assert usage["total_tokens"] == 150

    def test_missing_usage_defaults_to_zero(self):
        adapter = AnthropicAdapter()
        raw = {"content": [{"type": "text", "text": "x"}]}
        _, usage, _ = adapter._parse_response(raw)
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0


# ── Vendor call (HTTP plumbing) ────────────────────────────


class TestAnthropicVendorCall:
    def test_headers_use_x_api_key_not_bearer(self):
        """Anthropic uses x-api-key header, not the OpenAI
        Bearer scheme."""
        with patch(
            "core.adapters.llm.anthropic.get_config"
        ) as mock_cfg, patch(
            "core.adapters.llm._base.LLMBaseAdapter._post_json"
        ) as mock_post:
            mock_cfg.return_value.get.return_value = "sk-ant-key"
            mock_post.return_value = {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
            adapter = AnthropicAdapter()
            adapter._call_vendor(
                {"model": "x", "messages": []},
                capability=Capability.CHAT_COMPLETE,
            )
            args, kwargs = mock_post.call_args
            headers = kwargs.get("headers") or {}
            assert headers.get("x-api-key") == "sk-ant-key"
            assert "Authorization" not in headers
            assert (
                headers.get("anthropic-version")
                == _ANTHROPIC_VERSION
            )

    def test_endpoint_is_messages(self):
        with patch(
            "core.adapters.llm.anthropic.get_config"
        ) as mock_cfg, patch(
            "core.adapters.llm._base.LLMBaseAdapter._post_json"
        ) as mock_post:
            mock_cfg.return_value.get.return_value = "sk-ant"
            mock_post.return_value = {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
            adapter = AnthropicAdapter()
            adapter._call_vendor(
                {"model": "x", "messages": []},
                capability=Capability.CHAT_COMPLETE,
            )
            args, kwargs = mock_post.call_args
            url = args[0]
            assert url.endswith("/messages")


# ── Bootstrap registration ─────────────────────────────────


class TestAnthropicBootstrap:
    def test_register_all_includes_anthropic(self):
        from core.adapters.llm.bootstrap import (
            _LLM_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _LLM_ADAPTER_CLASSES]
        assert "anthropic" in names
        assert "openai" in names
        assert "groq" in names
