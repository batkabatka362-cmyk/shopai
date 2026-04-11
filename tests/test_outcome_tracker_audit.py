"""Tests for audit-pass-16 fixes in core/learning/outcome_tracker.

  1. record_decision() built `{k: v for k, v in decision.items()}`
     without checking that decision was actually a dict. A
     string / list / None argument crashed with AttributeError on
     `.items()`. Callers in heterogeneous paths sometimes pass the
     raw response object instead of a dict.
  2. record_outcome() used
     `outcome.get("success", safe_float(outcome.get("revenue")) > 0)`
     so:
     - if `success` was explicitly None, it returned None and the
       downstream filters bucket None as failure (silent
       misclassification of "outcome unknown")
     - if outcome itself was None or non-dict, the .get() call
       crashed
     - if `success` was a truthy string ("true", "yes"), it
       was stored verbatim and the truthy/falsy check still
       worked but no normalization happened
"""
import os
import tempfile

import pytest


@pytest.fixture
def tracker(monkeypatch):
    """OutcomeTracker writing to a fresh temp dir per test."""
    import core.learning.outcome_tracker as ot_mod
    tmp = tempfile.mkdtemp(prefix="shopai_outcomes_")
    monkeypatch.setattr(ot_mod, "_OUTCOME_DIR", tmp)
    return ot_mod.OutcomeTracker()


# ── record_decision non-dict input ───────────────────────────


class TestRecordDecisionDefensive:
    def test_dict_input_unchanged(self, tracker):
        tracker.record_decision("d1", "engine_x", {
            "action": "buy",
            "score": 7,
            "_internal": "drop_me",
            "request_id": "drop_me_too",
        })
        entries = tracker._load("engine_x")
        assert len(entries) == 1
        decision = entries[0]["decision"]
        assert decision["action"] == "buy"
        assert decision["score"] == 7
        # internal/strip keys removed
        assert "_internal" not in decision
        assert "request_id" not in decision

    def test_string_decision_does_not_crash(self, tracker):
        # Regression: previously this raised AttributeError on .items()
        tracker.record_decision("d2", "engine_x", "raw response text")
        entries = tracker._load("engine_x")
        assert len(entries) == 1
        assert entries[0]["decision"] == {"raw": "raw response text"}

    def test_none_decision_does_not_crash(self, tracker):
        tracker.record_decision("d3", "engine_x", None)
        entries = tracker._load("engine_x")
        assert len(entries) == 1
        assert "raw" in entries[0]["decision"]

    def test_list_decision_does_not_crash(self, tracker):
        tracker.record_decision("d4", "engine_x", ["item1", "item2"])
        entries = tracker._load("engine_x")
        assert len(entries) == 1
        assert "raw" in entries[0]["decision"]


# ── record_outcome bool normalization ────────────────────────


class TestRecordOutcomeNormalization:
    def test_explicit_true_stored_as_bool(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        assert tracker.record_outcome("d1", "engine_x", {"success": True}) is True
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is True

    def test_explicit_false_stored_as_bool(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        tracker.record_outcome("d1", "engine_x", {"success": False})
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is False

    def test_success_none_falls_back_to_revenue_signal(self, tracker):
        """Regression: previously `success=None` was stored as None
        and the downstream filters bucketed it as failure regardless
        of revenue. Now we fall back to revenue > 0."""
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        tracker.record_outcome("d1", "engine_x", {
            "success": None,
            "revenue": 100,
        })
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is True

    def test_success_none_no_revenue_is_false(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        tracker.record_outcome("d1", "engine_x", {
            "success": None,
            "revenue": 0,
        })
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is False

    def test_truthy_string_normalized(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        tracker.record_outcome("d1", "engine_x", {"success": "yes"})
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is True

    def test_falsy_string_normalized(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        tracker.record_outcome("d1", "engine_x", {"success": "no"})
        entries = tracker._load("engine_x")
        assert entries[0]["success"] is False

    def test_non_dict_outcome_does_not_crash(self, tracker):
        tracker.record_decision("d1", "engine_x", {"action": "x"})
        # Previously: outcome.get(...) on a string raised AttributeError
        result = tracker.record_outcome("d1", "engine_x", "raw response")
        assert result is True
        entries = tracker._load("engine_x")
        assert isinstance(entries[0]["outcome"], dict)
        assert entries[0]["success"] is False

    def test_unknown_decision_id_returns_false(self, tracker):
        # No matching decision → no update
        result = tracker.record_outcome("ghost", "engine_x", {"success": True})
        assert result is False


# ── Pattern detection works on normalized successes ─────────


class TestPatternsAfterNormalization:
    def test_success_filter_excludes_explicit_failures(self, tracker):
        for i in range(3):
            tracker.record_decision(f"d{i}", "engine_x", {"score": 8.0})
            tracker.record_outcome(f"d{i}", "engine_x", {"success": True})
        for i in range(3):
            tracker.record_decision(f"f{i}", "engine_x", {"score": 2.0})
            tracker.record_outcome(f"f{i}", "engine_x", {"success": False})

        patterns = tracker.get_winning_patterns("engine_x")
        assert patterns["successes"] == 3
        assert patterns["failures"] == 3
        assert patterns["success_rate"] == 0.5
