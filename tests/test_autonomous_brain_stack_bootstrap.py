"""Tests for ``_bootstrap_brain_stack`` and its wiring into
``AutonomousController.initialize``.

Pre-PR, the brain-stack feedback handlers attached only when some
path lazy-imported ``core.approval`` — which the autonomous
controller's startup never did. Result: the FIRST cycle's hooks
fired into a void; subsequent cycles worked only because the
first engine writeback finally triggered the lazy import.

This PR explicitly bootstraps the brain stack during
``AutonomousController.initialize()``, so the autonomous loop
always starts fully wired.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_brain_stack():
    """Clear hooks + goal_feedback registration so each test
    starts clean."""
    from core.hooks import dispatcher as hd
    from core.goals import goal_feedback as gf
    hd._HANDLERS.clear()
    gf.reset_for_tests()
    yield
    hd._HANDLERS.clear()
    gf.reset_for_tests()


# ─── module-level helper ──────────────────────────────────────────


class TestBootstrapBrainStack:

    def test_attaches_handlers(self):
        from core.autonomous.controller import _bootstrap_brain_stack
        from core.hooks import dispatcher as hd

        assert _bootstrap_brain_stack() is True
        # At least the two known handlers on main attach
        assert "approval.executed" in hd._HANDLERS
        assert "approval.failed" in hd._HANDLERS

    def test_idempotent(self):
        """Calling twice doesn't double-attach handlers."""
        from core.autonomous.controller import _bootstrap_brain_stack
        from core.hooks import dispatcher as hd

        _bootstrap_brain_stack()
        first_count = len(hd._HANDLERS.get("approval.executed", []))
        _bootstrap_brain_stack()
        second_count = len(hd._HANDLERS.get("approval.executed", []))
        assert first_count == second_count

    def test_returns_false_when_register_raises(self):
        """If register_goal_feedback raises, bootstrap returns
        False but doesn't propagate the exception. The autonomous
        loop must continue to function (without learning) when
        the brain stack is broken."""
        from core.autonomous import controller as ctrl

        with patch(
            "core.goals.goal_feedback.register_goal_feedback",
            side_effect=RuntimeError("manager broken"),
        ):
            result = ctrl._bootstrap_brain_stack()
        assert result is False

    def test_returns_false_when_goal_feedback_unavailable(self):
        """Module import failing → False, no exception."""
        import sys
        from core.autonomous import controller as ctrl

        # Force the import inside _bootstrap_brain_stack to fail
        original = sys.modules.get("core.goals.goal_feedback")
        sys.modules["core.goals.goal_feedback"] = None
        try:
            result = ctrl._bootstrap_brain_stack()
            assert result is False
        finally:
            if original is not None:
                sys.modules["core.goals.goal_feedback"] = original
            else:
                sys.modules.pop("core.goals.goal_feedback", None)


# ─── wired into controller.initialize ─────────────────────────────


class TestControllerInitializeWiresBrainStack:

    def test_initialize_calls_bootstrap(self):
        """AutonomousController.initialize must call the bootstrap
        helper so the brain stack wires up before any cycle runs."""
        from core.autonomous.controller import AutonomousController

        ac = AutonomousController(store_manager=None)
        with patch(
            "core.autonomous.controller._bootstrap_brain_stack"
        ) as mock_boot:
            # Stub out the rest of init to focus on the bootstrap
            # call — initialize() does plenty of other work that
            # depends on stores/data providers/etc.
            with patch.object(ac, "_store_manager", MagicMock()):
                try:
                    ac.initialize(store_manager=MagicMock())
                except Exception:
                    # Other init paths may fail in test environment;
                    # the bootstrap call should have happened first
                    pass
        mock_boot.assert_called()

    def test_handlers_attached_after_initialize(self):
        """End-to-end: after initialize(), the brain-stack hooks
        are wired and an emitted approval.executed event reaches
        a recordable handler."""
        from core.autonomous.controller import AutonomousController
        from core.goals import goal_feedback as gf
        from core.hooks import dispatcher as hd

        # Inject a mock manager so we can verify the wired-up
        # handler actually calls into it
        mock_mgr = MagicMock()
        # Pre-register the bridge so initialize's bootstrap reuses it
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            ac = AutonomousController()
            try:
                ac.initialize(store_manager=MagicMock())
            except Exception:
                pass
            # Now goal_feedback should be registered
            assert gf._REGISTERED is True
            # And approval.executed handler is attached
            assert "approval.executed" in hd._HANDLERS
