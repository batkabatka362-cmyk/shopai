"""Tests for engines._approval_prevet."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engines._approval_prevet import (
    PrevetRecommendation,
    is_enabled,
    prevet_action,
    prevet_batch,
)


def _fake_action(*, action_id="a1", engine="loyalty",
                 risk_class="additive", action_type="apply"):
    return SimpleNamespace(
        id=action_id,
        engine=engine,
        action_type=action_type,
        capability="SHOPIFY_X",
        risk_class=risk_class,
        params={},
        confidence=None,
    )


class TestEnvGate:

    def test_default_disabled(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        assert is_enabled() is False

    def test_enabled_when_set(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_PREVET", "1")
        assert is_enabled() is True


class TestHeuristicBaseline:
    """Deterministic recommendation when LLM unavailable."""

    def test_destructive_holds(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action(risk_class="destructive")
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={"engine": "x"},
        ):
            rec = prevet_action(action)
        assert rec.recommendation == "hold"
        assert "destructive" in rec.rationale.lower()
        assert "destructive_risk_class" in rec.flags

    def test_new_engine_holds(self, monkeypatch):
        """No outcome history -> hold."""
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action()
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "engine": "x",
                "recent_outcomes": {
                    "positive_count": 0,
                    "negative_count": 0,
                    "neutral_count": 0,
                },
            },
        ):
            rec = prevet_action(action)
        assert rec.recommendation == "hold"
        assert "new_engine" in rec.flags

    def test_strong_positive_history_additive_approves(
        self, monkeypatch,
    ):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action(risk_class="additive")
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "engine": "loyalty",
                "recent_outcomes": {
                    "positive_count": 9,
                    "negative_count": 1,
                    "neutral_count": 0,
                },
            },
        ):
            rec = prevet_action(action)
        assert rec.recommendation == "approve"
        assert rec.confidence > 0.7

    def test_strong_negative_rejects(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action(risk_class="additive")
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "engine": "loyalty",
                "recent_outcomes": {
                    "positive_count": 1,
                    "negative_count": 9,
                    "neutral_count": 0,
                },
            },
        ):
            rec = prevet_action(action)
        assert rec.recommendation == "reject"
        assert "negative_outcome_trend" in rec.flags

    def test_mixed_history_holds(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action(risk_class="additive")
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "engine": "loyalty",
                "recent_outcomes": {
                    "positive_count": 5,
                    "negative_count": 5,
                    "neutral_count": 0,
                },
            },
        ):
            rec = prevet_action(action)
        assert rec.recommendation == "hold"


class TestLLMConsultation:

    def test_disabled_means_baseline_only(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        action = _fake_action()
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "recent_outcomes": {
                    "positive_count": 9,
                    "negative_count": 1,
                    "neutral_count": 0,
                },
            },
        ):
            rec = prevet_action(action)
        # Baseline approves -- no [AI] prefix
        assert rec.recommendation == "approve"
        assert "[AI]" not in rec.rationale

    def test_llm_unavailable_falls_back(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_PREVET", "1")
        action = _fake_action()
        fake_llm = MagicMock()
        fake_llm.available = False
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "recent_outcomes": {
                    "positive_count": 9,
                    "negative_count": 1,
                    "neutral_count": 0,
                },
            },
        ), patch(
            "engines._ai_strategies._LLMClient",
            return_value=fake_llm,
        ):
            rec = prevet_action(action)
        # Falls back to baseline
        assert rec.recommendation == "approve"
        assert "[AI]" not in rec.rationale

    def test_llm_valid_response_used(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_PREVET", "1")
        action = _fake_action()
        fake_llm = MagicMock()
        fake_llm.available = True
        fake_llm.chat_json.return_value = {
            "recommendation": "reject",
            "confidence": 0.85,
            "rationale": "params look risky",
        }
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "recent_outcomes": {
                    "positive_count": 9,
                    "negative_count": 1,
                    "neutral_count": 0,
                },
            },
        ), patch(
            "engines._ai_strategies._LLMClient",
            return_value=fake_llm,
        ):
            rec = prevet_action(action)
        # LLM overrode the baseline approve -> reject
        assert rec.recommendation == "reject"
        assert "[AI]" in rec.rationale
        assert rec.confidence == 0.85

    def test_llm_invalid_recommendation_falls_back(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_AI_PREVET", "1")
        action = _fake_action()
        fake_llm = MagicMock()
        fake_llm.available = True
        fake_llm.chat_json.return_value = {
            "recommendation": "invalid_choice",
            "confidence": 0.9,
        }
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "recent_outcomes": {
                    "positive_count": 9,
                    "negative_count": 1,
                    "neutral_count": 0,
                },
            },
        ), patch(
            "engines._ai_strategies._LLMClient",
            return_value=fake_llm,
        ):
            rec = prevet_action(action)
        # Bad LLM output -> baseline
        assert rec.recommendation == "approve"


class TestBatch:

    def test_empty_batch(self):
        assert prevet_batch([]) == []

    def test_batch_returns_one_per_action(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_PREVET", raising=False)
        actions = [
            _fake_action(action_id="a"),
            _fake_action(action_id="b"),
            _fake_action(action_id="c"),
        ]
        with patch(
            "engines._approval_prevet._gather_engine_context",
            return_value={
                "recent_outcomes": {
                    "positive_count": 0,
                    "negative_count": 0,
                    "neutral_count": 0,
                },
            },
        ):
            results = prevet_batch(actions)
        assert len(results) == 3
        # Order preserved
        assert [r.action_id for r in results] == ["a", "b", "c"]
