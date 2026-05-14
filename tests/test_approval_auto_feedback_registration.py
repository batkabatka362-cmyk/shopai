"""Tests for the auto-registration of goal_feedback on
``core.approval`` import.

Before this PR, ``register_goal_feedback()`` was opt-in by design
but no production code path called it. The brain stack's EMA was
dormant in real deployments — engines emitted approval.executed /
failed / outcome.recorded hooks, but nothing listened, so the
recommender's effectiveness scores never moved.

Making ``core.approval`` self-attach the handlers on import fixes
that. Any consumer of the queue (CLI, API, autonomous loop)
transparently gets the feedback loop.

Coverage:
  - Handlers attach on package import
  - Auto-attach failure (goal_feedback raises) keeps queue usable
  - Idempotent — duplicate imports don't double-register
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset hooks + goal_feedback registration so each test sees
    a clean slate."""
    from core.hooks import dispatcher as hd
    from core.goals import goal_feedback as gf

    hd._HANDLERS.clear()
    gf.reset_for_tests()
    yield
    hd._HANDLERS.clear()
    gf.reset_for_tests()


class TestAutoRegistration:

    def test_handlers_attached_on_import(self):
        """A fresh import of core.approval wires the three
        approval.* handlers on the hooks dispatcher."""
        import core.approval
        importlib.reload(core.approval)

        from core.hooks import dispatcher as hd
        for name in (
            "approval.executed",
            "approval.failed",
            "approval.outcome.recorded",
        ):
            assert name in hd._HANDLERS, f"missing handler for {name}"
            assert len(hd._HANDLERS[name]) >= 1, name

    def test_REGISTERED_flag_set(self):
        import core.approval
        importlib.reload(core.approval)
        from core.goals import goal_feedback as gf
        assert gf._REGISTERED is True

    def test_idempotent_reimport(self):
        """Re-importing twice doesn't double-attach handlers
        (register_goal_feedback is itself idempotent)."""
        import core.approval
        importlib.reload(core.approval)
        importlib.reload(core.approval)

        from core.hooks import dispatcher as hd
        # Each handler appears exactly once
        for name in (
            "approval.executed",
            "approval.failed",
            "approval.outcome.recorded",
        ):
            assert len(hd._HANDLERS[name]) == 1, name

    def test_goal_feedback_import_failure_keeps_queue_usable(
        self, monkeypatch,
    ):
        """If goal_feedback module is broken, the approval queue
        must still import. Brain-stack edge stays dormant — same
        graceful degradation as before this PR."""
        # Build a broken core.goals.goal_feedback module
        import sys
        # Drop cached import so the next import re-evaluates
        sys.modules.pop("core.approval", None)

        # Force register_goal_feedback to raise on first call
        from core.goals import goal_feedback as gf

        def _broken(**kwargs):
            raise RuntimeError("simulated goals failure")

        monkeypatch.setattr(gf, "register_goal_feedback", _broken)

        # MUST NOT raise
        import core.approval
        importlib.reload(core.approval)

        # And the queue is still importable + usable
        from core.approval import get_approval_queue
        q = get_approval_queue()
        assert q is not None


class TestEndToEndAfterAutoRegister:

    def test_executed_hook_reaches_goal_manager(
        self, tmp_path, monkeypatch,
    ):
        """Full e2e: action lifecycle through the auto-registered
        feedback handlers. Disable the pytest hook gate so handlers
        actually fire."""
        from unittest.mock import MagicMock, patch
        from core.approval import queue as q
        from core.approval.queue import ApprovalQueue
        from core.goals import goal_feedback as gf

        # Reset registration and inject a mock manager via reload
        fresh_queue = ApprovalQueue(db_path=tmp_path / "approval.db")
        monkeypatch.setattr(q, "_INSTANCE", fresh_queue)

        # Re-register with mock manager
        gf.reset_for_tests()
        mock_mgr = MagicMock()
        gf.register_goal_feedback(manager=mock_mgr)

        with patch(
            "core.hooks.dispatcher._is_test_environment",
            return_value=False,
        ):
            a = fresh_queue.enqueue(
                engine="cart_recovery", action_type="mint_code",
                capability="X", params={}, narrative="",
            )
            fresh_queue.approve(a.id, decided_by="op")
            fresh_queue.attach_result(
                a.id, success=True, result={"code": "X1"},
            )

        # executed hook fired → manager called once
        assert mock_mgr.record_goal_outcome.call_count >= 1
        # Goal was attributed correctly
        goals_seen = {
            c.args[0]
            for c in mock_mgr.record_goal_outcome.call_args_list
        }
        assert "grow_customers" in goals_seen

        fresh_queue._conn.close()
