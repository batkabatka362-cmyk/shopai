"""Tests for ``core.brain.intent_llm.llm_classify`` + the
fallback hook in ``classify_intent``.

The fallback is OFF by default — it only fires when:
  1. ANTHROPIC_API_KEY is set in the env.
  2. The ``anthropic`` SDK is importable.
  3. The rule-based pass returned a below-floor confidence.

So the tests focus on:
  * No-op paths (key missing, SDK unavailable, no engine match
    in response, garbage response).
  * Happy path with a mocked SDK.
  * The router-level hook fires only when rule-based confidence
    is below floor; high-confidence rule matches are not
    overridden.
"""
from __future__ import annotations

import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ─── _build_client lazy-import ─────────────────────────────────


class TestSDKImportPath:

    def test_no_anthropic_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from core.brain.intent_llm import llm_classify

        result = llm_classify(
            "rewrite my product descriptions",
            candidate_engines=["content_generation"],
        )
        assert result is None

    def test_missing_anthropic_sdk_returns_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        # Simulate ImportError when the SDK isn't installed by
        # stuffing a placeholder that raises on attribute access.
        # Easier: patch the import at the function level.
        from core.brain import intent_llm

        with patch.object(intent_llm, "_build_client", return_value=None):
            result = intent_llm.llm_classify(
                "rewrite my product descriptions",
                candidate_engines=["content_generation"],
            )
        assert result is None

    def test_empty_text_short_circuits(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain.intent_llm import llm_classify

        for bad in ["", "   ", "\n\t"]:
            assert llm_classify(
                bad, candidate_engines=["content_generation"],
            ) is None

    def test_no_candidate_engines_short_circuits(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain.intent_llm import llm_classify

        assert llm_classify("anything", candidate_engines=[]) is None


# ─── happy path with mocked SDK ────────────────────────────────


def _stub_anthropic_response(json_text: str):
    """Build a fake Anthropic SDK response object whose
    ``content[0].text`` returns ``json_text``."""
    block = types.SimpleNamespace(type="text", text=json_text)
    return types.SimpleNamespace(content=[block])


class TestHappyPath:

    def test_clean_classification_returns_result(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "content_generation", "confidence": 0.82, '
            '"reasoning": "merchant wants to rewrite copy"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "I'd like fresh wording for my widgets, please",
                candidate_engines=[
                    "content_generation", "search_optimization",
                ],
                phrase_hints={
                    "content_generation": ["rewrite", "description"],
                },
            )
        assert result is not None
        assert result.engine == "content_generation"
        assert result.confidence == 0.82
        assert "merchant" in result.reasoning

    def test_phrase_hints_appear_in_prompt(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "loyalty", "confidence": 0.7, "reasoning": "x"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            intent_llm.llm_classify(
                "thank my best customers",
                candidate_engines=["loyalty"],
                phrase_hints={
                    "loyalty": ["loyalty program", "reward customer"],
                },
            )
        prompt = client.messages.create.call_args.kwargs["messages"][0][
            "content"
        ]
        # Hints landed in the prompt as inline context.
        assert "loyalty program" in prompt
        assert "thank my best customers" in prompt

    def test_confidence_clamped_to_unit_range(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        # Model returns out-of-range confidence — we clamp.
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "loyalty", "confidence": 99.0, "reasoning": "y"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "vip customers", candidate_engines=["loyalty"],
            )
        assert result is not None
        assert result.confidence == 1.0


# ─── parse failures collapse to None ───────────────────────────


class TestParseFailures:

    def test_unknown_engine_collapses_to_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "unknown", "confidence": 0.0, "reasoning": "no fit"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "weather forecast",
                candidate_engines=["loyalty", "discount_strategy"],
            )
        assert result is None

    def test_off_list_engine_collapses_to_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        # Model hallucinates an engine name not in the candidate
        # list — must not slip through.
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "fictional_engine", "confidence": 0.9, '
            '"reasoning": "i made it up"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "anything",
                candidate_engines=["loyalty", "discount_strategy"],
            )
        assert result is None

    def test_garbage_text_collapses_to_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            "this is not json at all",
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "anything",
                candidate_engines=["loyalty"],
            )
        assert result is None

    def test_network_error_collapses_to_none(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("network")
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "anything",
                candidate_engines=["loyalty"],
            )
        assert result is None

    def test_json_in_extra_prose_still_extracted(self, monkeypatch):
        # The model occasionally adds prose around the JSON
        # despite the prompt; the regex extracts the first
        # ``{...}`` substring.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            'Sure! {"engine": "loyalty", "confidence": 0.8, '
            '"reasoning": "vip"} ← that was my answer',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_llm.llm_classify(
                "anything", candidate_engines=["loyalty"],
            )
        assert result is not None
        assert result.engine == "loyalty"


# ─── classify_intent fallback hook ─────────────────────────────


class TestRouterFallbackHook:

    def test_high_confidence_rule_match_does_not_invoke_llm(
        self, monkeypatch,
    ):
        # Even with a key set, a clean rule match must NOT call
        # the LLM — the rules are cheaper and trustworthy.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_router

        with patch.object(
            intent_router, "_try_llm_fallback",
        ) as mock_fallback:
            result = intent_router.classify_intent(
                "create a 10% promo code",
            )
        mock_fallback.assert_not_called()
        assert result.source == "rules"
        assert result.engine == "discount_strategy"

    def test_below_floor_invokes_llm_when_available(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm, intent_router

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "content_generation", "confidence": 0.7, '
            '"reasoning": "rewrite request inferred from context"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_router.classify_intent(
                # Phrase that doesn't match any rule keyword:
                "make my listings sound more poetic, please",
            )
        # LLM took over.
        assert result.source == "llm"
        assert result.engine == "content_generation"
        assert result.confidence == 0.7

    def test_below_floor_no_key_falls_through_to_no_match(
        self, monkeypatch,
    ):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from core.brain import intent_router

        result = intent_router.classify_intent(
            "make my listings sound more poetic, please",
        )
        # No LLM available → original "weak match" path runs.
        assert result.source == "rules"
        assert result.engine is None

    def test_llm_unknown_falls_back_to_no_match(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_llm, intent_router

        client = MagicMock()
        client.messages.create.return_value = _stub_anthropic_response(
            '{"engine": "unknown", "confidence": 0.0, "reasoning": "n/a"}',
        )
        with patch.object(intent_llm, "_build_client", return_value=client):
            result = intent_router.classify_intent(
                "weather report for tomorrow",
            )
        assert result.engine is None
        assert result.source == "rules"

    def test_llm_exception_does_not_propagate(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        from core.brain import intent_router

        with patch(
            "core.brain.intent_llm.llm_classify",
            side_effect=RuntimeError("client crashed"),
        ):
            result = intent_router.classify_intent(
                "make my listings sound more poetic, please",
            )
        # Crash swallowed → fall through to "no match".
        assert result.engine is None
        assert result.source == "rules"
