"""Tests for the shared AGI context-capture helper
(``engines._agi_context``).

The helper bridges Phase 6/7 engine writers to the Phase 2 AGI
stack (world model + decision retrieval). Verifies:

  - Test-environment guard short-circuits (no real DB hits)
  - When guard disabled: snapshot + retrieval are called
  - Metrics rollup shape (similar_count, polarity flags,
    avg_relevance)
  - Resilience: import failures / probe raises don't propagate
"""
from __future__ import annotations

from unittest.mock import patch

from engines._agi_context import (
    capture_decision_context,
    _summarize_similar,
)


# ─── _summarize_similar helper ───────────────────────────────


class TestSummarizeSimilar:

    def test_empty(self):
        s = _summarize_similar([])
        assert s["similar_count"] == 0
        assert s["recent_positive"] is False
        assert s["recent_negative"] is False
        assert s["avg_relevance"] == 0.0

    def test_mixed_polarities(self):
        s = _summarize_similar([
            {
                "relevance": 0.8,
                "outcome_summary": {
                    "has_positive": True, "has_negative": False,
                },
            },
            {
                "relevance": 0.6,
                "outcome_summary": {
                    "has_positive": False, "has_negative": True,
                },
            },
            {
                "relevance": 0.4,
                "outcome_summary": {
                    "has_positive": False, "has_negative": False,
                },
            },
        ])
        assert s["similar_count"] == 3
        assert s["recent_positive"] is True
        assert s["recent_negative"] is True
        # (0.8 + 0.6 + 0.4) / 3 = 0.6
        assert abs(s["avg_relevance"] - 0.6) < 0.01

    def test_missing_outcome_summary(self):
        s = _summarize_similar([
            {"relevance": 0.5},  # no outcome_summary at all
        ])
        # Should not crash; polarities default to False
        assert s["similar_count"] == 1
        assert s["recent_positive"] is False
        assert s["recent_negative"] is False


# ─── capture_decision_context ────────────────────────────────


class TestCaptureContext:

    def test_test_env_guard_short_circuits(self):
        """Under pytest, the guard returns an empty metrics dict
        without touching the AGI modules."""
        # PYTEST_CURRENT_TEST is set automatically -- the guard
        # short-circuits.
        result = capture_decision_context(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"customer_id": "gid://shopify/Customer/1"},
        )
        assert result == {"metrics": {}}

    def test_disabled_guard_calls_retrieval(self):
        """Patch the guard off; the retriever should be invoked
        and its output reflected in metrics."""
        with patch(
            "engines._agi_context._is_test_environment",
            return_value=False,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            retriever_cls.return_value.retrieve.return_value = [
                {
                    "relevance": 0.9,
                    "outcome_summary": {
                        "has_positive": True, "has_negative": False,
                    },
                },
            ]
            result = capture_decision_context(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"customer_id": "x"},
            )
        assert "similar" in result
        assert len(result["similar"]) == 1
        m = result["metrics"]
        assert m["similar_count"] == 1
        assert m["recent_positive"] is True
        assert abs(m["avg_relevance"] - 0.9) < 0.01

    def test_retrieval_raise_degrades_silently(self):
        with patch(
            "engines._agi_context._is_test_environment",
            return_value=False,
        ), patch(
            "core.decision_retrieval.DecisionRetrieval",
            side_effect=RuntimeError("module down"),
        ):
            result = capture_decision_context(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"customer_id": "x"},
            )
        # No raise, no similar -- just empty metrics
        assert result["metrics"] == {}

    def test_with_store_id_calls_snapshot(self):
        with patch(
            "engines._agi_context._is_test_environment",
            return_value=False,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls, patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            wm_cls.return_value.snapshot.return_value = {
                "store_id": "test", "stats": {},
            }
            retriever_cls.return_value.retrieve.return_value = []
            result = capture_decision_context(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"customer_id": "x"},
                store_id="test",
            )
        assert "snapshot" in result
        assert result["snapshot"]["store_id"] == "test"

    def test_without_store_id_skips_snapshot(self):
        with patch(
            "engines._agi_context._is_test_environment",
            return_value=False,
        ), patch(
            "core.world_model.WorldModel",
        ) as wm_cls, patch(
            "core.decision_retrieval.DecisionRetrieval",
        ) as retriever_cls:
            retriever_cls.return_value.retrieve.return_value = []
            result = capture_decision_context(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"customer_id": "x"},
                # store_id omitted -- snapshot section skipped
            )
        assert "snapshot" not in result
        wm_cls.assert_not_called()
