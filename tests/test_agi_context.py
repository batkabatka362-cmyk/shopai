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
    GUARDRAIL_ENGINES,
    guardrail_enabled,
    guardrail_state,
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


# ─── Guardrail roster + state ────────────────────────────────


class TestGuardrailRoster:
    """``GUARDRAIL_ENGINES`` is the canonical list of engines
    with v2 guardrail wiring. ``guardrail_state()`` is the
    cheap env-var fan-out the operator CLI consumes."""

    def test_roster_is_immutable_tuple(self):
        """A tuple, not a list — accidental mutation would
        silently corrupt downstream callers."""
        assert isinstance(GUARDRAIL_ENGINES, tuple)
        # All entries are non-empty strings.
        assert all(
            isinstance(e, str) and e
            for e in GUARDRAIL_ENGINES
        )

    def test_roster_includes_phase_6_7_minters(self):
        """The six minters wired up in PRs #245 + #250 must all
        be in the roster. If a future PR drops one, this test
        catches the regression."""
        for engine in (
            "loyalty",
            "cart_recovery",
            "browse_recovery",
            "email_marketing",
            "wholesale_b2b",
            "discount_strategy",
        ):
            assert engine in GUARDRAIL_ENGINES

    def test_state_keys_match_roster(self, monkeypatch):
        """``guardrail_state()`` returns one entry per roster
        engine, no extras."""
        for engine in GUARDRAIL_ENGINES:
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        state = guardrail_state()
        assert set(state.keys()) == set(GUARDRAIL_ENGINES)

    def test_state_all_off_by_default(self, monkeypatch):
        for engine in GUARDRAIL_ENGINES:
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        state = guardrail_state()
        assert all(v is False for v in state.values())

    def test_state_reflects_env_var_per_engine(self, monkeypatch):
        for engine in GUARDRAIL_ENGINES:
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        # Enable just loyalty.
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")
        state = guardrail_state()
        assert state["loyalty"] is True
        # The other five remain off.
        for engine in GUARDRAIL_ENGINES:
            if engine != "loyalty":
                assert state[engine] is False

    def test_state_uses_guardrail_enabled_semantics(
        self, monkeypatch,
    ):
        """``guardrail_state`` and ``guardrail_enabled`` must
        agree on every truthy / falsy value."""
        for engine in GUARDRAIL_ENGINES:
            monkeypatch.delenv(
                f"SHOPAI_{engine.upper()}_AGI_GUARDRAIL",
                raising=False,
            )
        for truthy in ("1", "true", "yes", "on"):
            monkeypatch.setenv(
                "SHOPAI_LOYALTY_AGI_GUARDRAIL", truthy,
            )
            assert guardrail_enabled("loyalty") is True
            assert guardrail_state()["loyalty"] is True
        for falsy in ("0", "false", "no", "off", ""):
            monkeypatch.setenv(
                "SHOPAI_LOYALTY_AGI_GUARDRAIL", falsy,
            )
            assert guardrail_enabled("loyalty") is False
            assert guardrail_state()["loyalty"] is False
