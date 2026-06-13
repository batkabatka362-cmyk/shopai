"""Tests for engines._empire_summarizer."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from engines._empire_summarizer import (
    EmpireSummary,
    _deterministic_summary,
    summarize_empire,
)


class TestDeterministicSummary:

    def test_handles_empty_facts(self):
        s = _deterministic_summary({})
        assert isinstance(s, str)
        # Empty facts -> the "No empire state" fallback OR
        # the "no cycle yet" + "no active issues" path
        assert len(s) > 0

    def test_includes_store_count(self):
        s = _deterministic_summary({"store_count": 5})
        assert "5" in s

    def test_includes_revenue_when_positive(self):
        s = _deterministic_summary({
            "attributed_revenue_7d": 1234.56,
        })
        assert "1,234" in s or "1234" in s

    def test_omits_revenue_when_zero(self):
        s = _deterministic_summary({
            "attributed_revenue_7d": 0,
        })
        assert "attributed revenue" not in s.lower()

    def test_lists_issues(self):
        s = _deterministic_summary({
            "regression_alert_count": 2,
            "spend_breach_count": 1,
        })
        assert "2 revenue regression" in s
        assert "1 spend cap" in s

    def test_clean_state_no_issues_line(self):
        s = _deterministic_summary({
            "store_count": 1,
            "last_cycle_age_hours": 1.0,
            "last_cycle_verdict": "clean",
            "last_cycle_ok": 5,
            "last_cycle_errors": 0,
        })
        assert "no active issues" in s.lower()

    def test_pending_approvals_surfaced(self):
        s = _deterministic_summary({"pending_count": 7})
        assert "7" in s
        assert "approvals digest" in s

    def test_transfer_candidates_surfaced(self):
        s = _deterministic_summary({
            "transfer_candidate_count": 5,
            "transfer_top_engine": "loyalty",
        })
        assert "5" in s
        assert "transfer" in s.lower()
        assert "loyalty" in s

    def test_zero_transfer_candidates_silent(self):
        s = _deterministic_summary({
            "transfer_candidate_count": 0,
        })
        assert "transfer" not in s.lower()


class TestAIRefine:

    def test_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_AI_STRATEGY", raising=False)
        summary = summarize_empire()
        # Falls back to deterministic
        assert summary.used_llm is False

    def test_llm_unavailable_falls_back(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        fake_llm = MagicMock()
        fake_llm.available = False
        with patch(
            "engines._ai_strategies._LLMClient",
            return_value=fake_llm,
        ):
            summary = summarize_empire()
        assert summary.used_llm is False

    def test_llm_refined_summary_used(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_AI_STRATEGY", "1")
        fake_llm = MagicMock()
        fake_llm.available = True
        fake_llm.chat_json.return_value = {
            "summary": (
                "20 stores running smoothly; one urgent "
                "regression on store-3."
            ),
        }
        with patch(
            "engines._ai_strategies._LLMClient",
            return_value=fake_llm,
        ):
            summary = summarize_empire()
        assert summary.used_llm is True
        assert "20 stores" in summary.text


class TestEmpireSummaryShape:

    def test_returns_required_fields(self):
        summary = summarize_empire()
        assert isinstance(summary, EmpireSummary)
        assert isinstance(summary.text, str)
        assert isinstance(summary.used_llm, bool)
        assert isinstance(summary.key_facts, dict)


class TestPerStoreSummary:
    """Wave 69: per-store summary via store_id filter."""

    def test_store_filter_in_key_facts(self):
        summary = summarize_empire(store_id="store-x")
        assert summary.key_facts.get("scope_store_id") == "store-x"

    def test_deterministic_mentions_store_name(self):
        s = _deterministic_summary({
            "scope_store_id": "store-7",
        })
        assert "store-7" in s

    def test_fleet_default_when_no_store(self):
        summary = summarize_empire()
        assert (
            summary.key_facts.get("scope_store_id") is None
        )
