"""Tests for OpenAIAdapter -- W963-104."""
from __future__ import annotations

from unittest.mock import patch

from core.adapters.base import Capability
from core.adapters.llm.openai import OpenAIAdapter


# ── Configuration ─────────────────────────────────────────


class TestOpenAIConfiguration:
    def test_is_configured_returns_false_without_key(self):
        with patch(
            "core.adapters.llm._openai_compat.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = ""
            adapter = OpenAIAdapter()
            assert adapter.is_configured() is False

    def test_is_configured_returns_true_with_key(self):
        with patch(
            "core.adapters.llm._openai_compat.get_config"
        ) as mock_cfg:
            mock_cfg.return_value.get.return_value = "sk-test"
            adapter = OpenAIAdapter()
            assert adapter.is_configured() is True

    def test_config_alias_is_openai(self):
        adapter = OpenAIAdapter()
        assert adapter.config_alias == "openai"


# ── Metadata ───────────────────────────────────────────────


class TestOpenAIMetadata:
    def test_name(self):
        assert OpenAIAdapter.name == "openai"

    def test_base_url_is_openai(self):
        adapter = OpenAIAdapter()
        assert "api.openai.com" in adapter.base_url

    def test_default_model_is_4o_mini(self):
        """gpt-4o-mini balances cost (~5% of gpt-4o) with
        quality good enough for the consultant overlay's
        baseline refinements."""
        adapter = OpenAIAdapter()
        assert adapter.model_default == "gpt-4o-mini"

    def test_capabilities_include_premium_paths(self):
        caps = OpenAIAdapter.capabilities
        assert Capability.CHAT_COMPLETE in caps
        assert Capability.REASON_DEEP in caps
        assert Capability.CODE_GENERATE in caps
        assert Capability.LONG_CONTEXT in caps

    def test_priority_below_groq(self):
        """Groq is faster + free, so wins router default for
        chat completion. OpenAI is opt-in for premium
        reasoning tasks."""
        from core.adapters.llm.groq import GroqAdapter
        assert OpenAIAdapter.priority < GroqAdapter.priority

    def test_endpoint_url_path(self):
        adapter = OpenAIAdapter()
        url = adapter._endpoint_url()
        assert url.endswith("/chat/completions")


# ── Bootstrap registration ─────────────────────────────────


class TestOpenAIBootstrap:
    def test_register_all_includes_openai(self):
        from core.adapters.llm.bootstrap import (
            _LLM_ADAPTER_CLASSES,
        )
        names = [cls.name for cls in _LLM_ADAPTER_CLASSES]
        assert "openai" in names
        # Sanity: existing adapters still registered
        assert "groq" in names
        assert "deepseek" in names
