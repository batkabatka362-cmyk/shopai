"""Tests for the outcome → goal_feedback wiring.

PR #112 added per-action outcome storage. The next loop closure:
when a Shopify webhook annotates an action with a positive
outcome (customer redeemed code → orders/create) or negative
outcome (refund), that downstream-reality signal should refine
the brain stack's EMA — not just the immediate
"mutation succeeded" signal.

This file covers:
  - record_outcome emits the ``approval.outcome.recorded`` hook
  - goal_feedback subscribes to that hook
  - polarity → signed metrics (positive/negative/neutral)
  - unmapped engines skip silently
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """The hooks dispatcher short-circuits under pytest by default;
    these tests need handlers to actually fire."""
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def fresh_hooks(monkeypatch):
    """Reset the hooks dispatcher so this test's handlers don't
    inherit state from prior tests."""
    from core.hooks import dispatcher as d
    d._HANDLERS.clear()
    yield
    d._HANDLERS.clear()


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch, fresh_hooks):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def fresh_feedback(monkeypatch):
    from core.goals import goal_feedback as gf
    gf.reset_for_tests()
    yield gf
    gf.reset_for_tests()


def _seed_executed(queue, *, engine: str = "cart_recovery", code: str = "X1"):
    a = queue.enqueue(
        engine=engine, action_type="mint_code", capability="X",
        params={}, narrative="",
    )
    queue.approve(a.id, decided_by="op")
    queue.attach_result(a.id, success=True, result={"code": code})
    return a


# ─── record_outcome emits the hook ────────────────────────────────


class TestRecordOutcomeHook:

    def test_emits_hook_on_success(self, isolated_queue, fresh_hooks):
        from core.hooks import register

        captured: list[dict] = []
        register(
            "approval.outcome.recorded",
            lambda event: captured.append(event),
        )

        a = _seed_executed(isolated_queue)
        isolated_queue.record_outcome(
            a.id, topic="orders/create",
            polarity="positive",
            metrics={"revenue": 19.99},
            source_event="order_1",
        )
        assert len(captured) == 1
        data = captured[0]["data"]
        assert data["action_id"] == a.id
        assert data["engine"] == "cart_recovery"
        assert data["action_type"] == "mint_code"
        assert data["topic"] == "orders/create"
        assert data["polarity"] == "positive"
        assert data["metrics"] == {"revenue": 19.99}
        assert data["source_event"] == "order_1"

    def test_no_hook_on_unknown_action(
        self, isolated_queue, fresh_hooks,
    ):
        from core.hooks import register

        captured: list[dict] = []
        register(
            "approval.outcome.recorded",
            lambda event: captured.append(event),
        )
        ok = isolated_queue.record_outcome(
            "appr_does_not_exist", topic="orders/create",
        )
        assert ok is False
        # Hook MUST NOT fire for no-op
        assert captured == []


# ─── goal_feedback consumes the hook ──────────────────────────────


class TestOutcomeFeedbackWiring:

    def test_positive_outcome_records_goal(
        self, isolated_queue, fresh_feedback,
    ):
        mock_mgr = MagicMock()
        mock_mgr.record_goal_outcome = MagicMock()
        assert fresh_feedback.register_goal_feedback(
            manager=mock_mgr,
        )

        a = _seed_executed(isolated_queue)
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="orders/create",
            polarity="positive",
            metrics={"revenue": 25.0},
        )
        mock_mgr.record_goal_outcome.assert_called_once_with(
            "grow_customers",
            {"health_delta": 1.0, "revenue_delta": 25.0},
        )

    def test_negative_outcome_flips_signs(
        self, isolated_queue, fresh_feedback,
    ):
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue)
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="refunds/create",
            polarity="negative",
            metrics={"revenue": 25.0},
        )
        mock_mgr.record_goal_outcome.assert_called_once_with(
            "grow_customers",
            {"health_delta": -1.0, "revenue_delta": -25.0},
        )

    def test_neutral_outcome_skips_recording(
        self, isolated_queue, fresh_feedback,
    ):
        """orders/updated and other neutral events shouldn't move
        the EMA — they'd otherwise inflate sample count without
        moving the mean."""
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue)
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="orders/updated", polarity="neutral",
        )
        mock_mgr.record_goal_outcome.assert_not_called()

    def test_no_revenue_metric_still_records_health(
        self, isolated_queue, fresh_feedback,
    ):
        """Webhook payload without revenue field still drives EMA
        via health_delta alone — better than no signal at all."""
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue)
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="orders/create", polarity="positive",
        )
        mock_mgr.record_goal_outcome.assert_called_once_with(
            "grow_customers", {"health_delta": 1.0},
        )

    def test_unmapped_engine_skips_recording(
        self, isolated_queue, fresh_feedback,
    ):
        """An engine not in ENGINE_GOAL_MAP doesn't have an
        attributable goal — the EMA stays clean."""
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue, engine="totally_unmapped_xyz")
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={"revenue": 10.0},
        )
        mock_mgr.record_goal_outcome.assert_not_called()

    def test_invalid_revenue_value_ignored(
        self, isolated_queue, fresh_feedback,
    ):
        """A non-numeric revenue field doesn't crash — just drops
        revenue_delta and records health alone."""
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue)
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={"revenue": "not_a_number"},
        )
        mock_mgr.record_goal_outcome.assert_called_once_with(
            "grow_customers", {"health_delta": 1.0},
        )

    def test_manager_raises_caught(
        self, isolated_queue, fresh_feedback,
    ):
        """record_goal_outcome raising must not propagate up
        through the hooks fan-out — one rogue feedback event can't
        crash the queue."""
        mock_mgr = MagicMock()
        mock_mgr.record_goal_outcome.side_effect = RuntimeError("boom")
        fresh_feedback.register_goal_feedback(manager=mock_mgr)
        a = _seed_executed(isolated_queue)

        # MUST NOT raise
        isolated_queue.record_outcome(
            a.id, topic="orders/create", polarity="positive",
        )

    def test_two_engines_attribute_to_their_goals(
        self, isolated_queue, fresh_feedback,
    ):
        """cart_recovery (grow_customers) and dynamic_pricing
        (maximize_profit) outcomes go to different goals."""
        mock_mgr = MagicMock()
        fresh_feedback.register_goal_feedback(manager=mock_mgr)

        cart = _seed_executed(isolated_queue, engine="cart_recovery")
        price = _seed_executed(isolated_queue, engine="dynamic_pricing")
        mock_mgr.record_goal_outcome.reset_mock()

        isolated_queue.record_outcome(
            cart.id, topic="orders/create", polarity="positive",
        )
        isolated_queue.record_outcome(
            price.id, topic="orders/create", polarity="positive",
        )
        # Two calls — different goals
        goals_seen = {
            c.args[0]
            for c in mock_mgr.record_goal_outcome.call_args_list
        }
        assert goals_seen == {"grow_customers", "maximize_profit"}
