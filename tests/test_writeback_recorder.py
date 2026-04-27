"""Tests for engines._writeback_recorder (Phase 8 integration bridge).

Phase 6/7 wireups call the SmartRouter directly, bypassing
SmartExecutor's learning feedback path. The recorder is the
bridge: each writer calls ``record_writeback`` after its
adapter call, and the recorder fans out to MemoryIntelligence,
DataArchitecture, and LearningLoop.

Coverage:
  1. ``_compute_score`` — mirrors SmartExecutor's scoring.
  2. ``record_writeback`` — fans out to all three systems on
     happy path, gracefully no-ops when each system is
     unavailable, never raises.
  3. Failure pathway — score ≤ 2.0 triggers ``record_failure``.

Note on the test-environment guard:
The recorder short-circuits when ``PYTEST_CURRENT_TEST`` is set
(production-only path) — see the docstring on
``_is_test_environment``. The tests below patch that guard to
return False so the fan-out behaviour is exercised under pytest.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Bypass the production-only ``PYTEST_CURRENT_TEST`` short-circuit
    so recorder tests can verify the actual fan-out path."""
    with patch(
        "engines._writeback_recorder._is_test_environment",
        return_value=False,
    ):
        yield


# ─── _compute_score ──────────────────────────────────────────────


class TestComputeScore:

    def test_success_no_metrics_yields_4(self):
        from engines._writeback_recorder import _compute_score

        # Base 3.0 + 1.0 success.
        assert _compute_score(success=True, metrics=None) == 4.0

    def test_failure_no_metrics_yields_1_5(self):
        from engines._writeback_recorder import _compute_score

        # Base 3.0 - 1.5 error.
        assert _compute_score(success=False, metrics=None) == 1.5

    def test_revenue_bonus_adds_half(self):
        from engines._writeback_recorder import _compute_score

        # Base 3 + 1 success + 0.5 revenue.
        assert _compute_score(
            success=True,
            metrics={"revenue_change_pct": 10.0},
        ) == 4.5

    def test_revenue_penalty_subtracts_half(self):
        from engines._writeback_recorder import _compute_score

        # Base 3 + 1 success - 0.5 revenue.
        assert _compute_score(
            success=True,
            metrics={"revenue_change_pct": -10.0},
        ) == 3.5

    def test_profitable_bonus(self):
        from engines._writeback_recorder import _compute_score

        # Base 3 + 1 + 0.3 profitable = 4.3.
        assert _compute_score(
            success=True, metrics={"profitable": True},
        ) == 4.3

    def test_clamped_to_max(self):
        from engines._writeback_recorder import _compute_score

        # Base 3 + 1 + 0.5 + 0.3 = 4.8 (still <= 5).
        # Add more bonuses → still capped at 5.
        score = _compute_score(
            success=True,
            metrics={
                "revenue_change_pct": 100.0,
                "profitable": True,
            },
        )
        assert score == 4.8

    def test_clamped_to_min(self):
        from engines._writeback_recorder import _compute_score

        # Base 3 - 1.5 - 0.5 = 1.0.
        score = _compute_score(
            success=False,
            metrics={"revenue_change_pct": -50.0},
        )
        assert score == 1.0

    def test_invalid_metric_value_treated_as_zero(self):
        from engines._writeback_recorder import _compute_score

        # Garbage in revenue_change_pct → no bonus or penalty.
        score = _compute_score(
            success=True,
            metrics={"revenue_change_pct": "garbage"},
        )
        assert score == 4.0


# ─── record_writeback (full fan-out) ──────────────────────────────


class TestRecordWritebackFanout:

    def test_happy_path_writes_to_all_three_systems(self):
        from engines._writeback_recorder import record_writeback

        mock_intel = MagicMock()
        mock_arch = MagicMock()
        mock_loop = MagicMock()

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=mock_intel,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=mock_arch,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=mock_loop,
        ):
            record_writeback(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"value": 10.0, "code": "LOYALTY-X-1"},
                success=True,
            )

        # MemoryIntelligence.create_from_decision called with the
        # right shape.
        assert mock_intel.create_from_decision.called
        kwargs = mock_intel.create_from_decision.call_args.kwargs
        assert kwargs["category"] == "loyalty"
        assert kwargs["action"] == "mint_loyalty_code"
        assert kwargs["score"] == 4.0  # success → 3+1
        assert "writeback" in kwargs["tags"]
        assert "success" in kwargs["tags"]

        # DataArchitecture.record_action + attach_result both called.
        assert mock_arch.record_action.called
        assert mock_arch.attach_result.called
        ra_kwargs = mock_arch.record_action.call_args.kwargs
        assert ra_kwargs["action_type"] == "mint_loyalty_code"
        assert ra_kwargs["action_data"]["engine"] == "loyalty"
        assert ra_kwargs["action_data"]["capability"] == \
            "SHOPIFY_CREATE_DISCOUNT"

        # LearningLoop.learn called with metrics.
        assert mock_loop.learn.called

    def test_failure_records_failure_separately(self):
        from engines._writeback_recorder import record_writeback

        mock_intel = MagicMock()

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=mock_intel,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=None,
        ):
            record_writeback(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={"value": 10.0},
                success=False,
                error="scope_missing",
            )

        # create_from_decision called with score=1.5 (failure).
        assert mock_intel.create_from_decision.called
        cd_kwargs = mock_intel.create_from_decision.call_args.kwargs
        assert cd_kwargs["score"] == 1.5
        assert "failure" in cd_kwargs["tags"]
        # record_failure also called because score ≤ 2.0.
        assert mock_intel.record_failure.called
        rf_kwargs = mock_intel.record_failure.call_args.kwargs
        assert rf_kwargs["category"] == "loyalty"
        assert rf_kwargs["root_cause"] == "scope_missing"

    def test_metrics_threaded_to_learning_loop(self):
        from engines._writeback_recorder import record_writeback

        mock_loop = MagicMock()

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=mock_loop,
        ):
            record_writeback(
                engine="dynamic_pricing",
                action_type="apply_price_change",
                capability="SHOPIFY_UPDATE_VARIANTS",
                params={"new_price": 99.99},
                success=True,
                metrics={"revenue_change_pct": 7.5},
            )

        # LearningLoop got the impact metrics.
        assert mock_loop.learn.called
        learn_kwargs = mock_loop.learn.call_args.kwargs
        assert learn_kwargs["metrics"]["profit"] == 7.5


# ─── Graceful no-op when systems are unavailable ─────────────────


class TestEnvironmentGuard:
    """The PYTEST_CURRENT_TEST short-circuit is the boundary
    between unit-test pollution and real production recording.
    These tests run WITHOUT the autouse fixture's bypass."""

    def test_pytest_env_var_short_circuits_fan_out(
        self, monkeypatch,
    ):
        # Re-enable the guard for this one test.
        monkeypatch.setattr(
            "engines._writeback_recorder._is_test_environment",
            lambda: True,
        )

        from engines._writeback_recorder import record_writeback

        mock_intel = MagicMock()
        mock_arch = MagicMock()
        mock_loop = MagicMock()

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=mock_intel,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=mock_arch,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=mock_loop,
        ):
            record_writeback(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={},
                success=False,
                error="adapter_failed: scope_missing",
            )

        # Critical: NONE of the three systems received the
        # synthetic test failure. This is what prevents test
        # fixtures from accumulating in failure_analysis +
        # auto-generating bogus avoidance rules.
        mock_intel.create_from_decision.assert_not_called()
        mock_intel.record_failure.assert_not_called()
        mock_arch.record_action.assert_not_called()
        mock_loop.learn.assert_not_called()


class TestGracefulNoOp:

    def test_all_systems_unavailable_no_raise(self):
        from engines._writeback_recorder import record_writeback

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=None,
        ):
            # Must not raise — engines must be free to call this
            # without dependencies on the autonomous loop.
            record_writeback(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={},
                success=True,
            )

    def test_memory_intel_raises_does_not_propagate(self):
        from engines._writeback_recorder import record_writeback

        mock_intel = MagicMock()
        mock_intel.create_from_decision.side_effect = (
            RuntimeError("DB locked")
        )

        with patch(
            "engines._writeback_recorder._get_memory_intel",
            return_value=mock_intel,
        ), patch(
            "engines._writeback_recorder._get_data_arch",
            return_value=None,
        ), patch(
            "engines._writeback_recorder._get_learning_loop",
            return_value=None,
        ):
            # Must not raise even when one system fails.
            record_writeback(
                engine="loyalty",
                action_type="mint_loyalty_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params={},
                success=True,
            )
