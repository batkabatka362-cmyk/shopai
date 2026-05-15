"""Tests for the brain-stack bootstrap wired into
``MainOrchestrator.initialize``.

Pre-PR, the brain-stack feedback handlers attached only when some
path lazy-imported ``core.approval``. ``MainOrchestrator``-based
flows (``shopai server``, direct API task submission, anything
not going through the autonomous controller) never imported the
queue eagerly. Result: the first few approval events fired into
a void; eventually a writeback lazy-imported the queue and the
handlers attached belatedly.

This regression test locks in the bootstrap call.
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
        from core.orchestrator.main_orchestrator import _bootstrap_brain_stack
        from core.hooks import dispatcher as hd

        assert _bootstrap_brain_stack() is True
        assert "approval.executed" in hd._HANDLERS
        assert "approval.failed" in hd._HANDLERS

    def test_idempotent(self):
        from core.orchestrator.main_orchestrator import _bootstrap_brain_stack
        from core.hooks import dispatcher as hd

        _bootstrap_brain_stack()
        first = len(hd._HANDLERS.get("approval.executed", []))
        _bootstrap_brain_stack()
        second = len(hd._HANDLERS.get("approval.executed", []))
        assert first == second

    def test_returns_false_on_register_failure(self):
        from core.orchestrator import main_orchestrator as mo

        with patch(
            "core.goals.goal_feedback.register_goal_feedback",
            side_effect=RuntimeError("manager broken"),
        ):
            assert mo._bootstrap_brain_stack() is False

    def test_returns_false_when_goal_feedback_unavailable(self):
        import sys
        from core.orchestrator import main_orchestrator as mo

        original = sys.modules.get("core.goals.goal_feedback")
        sys.modules["core.goals.goal_feedback"] = None
        try:
            assert mo._bootstrap_brain_stack() is False
        finally:
            if original is not None:
                sys.modules["core.goals.goal_feedback"] = original
            else:
                sys.modules.pop("core.goals.goal_feedback", None)


# ─── wired into initialize ────────────────────────────────────────


class TestInitializeCallsBootstrap:

    def test_initialize_invokes_bootstrap(self):
        """``MainOrchestrator.initialize`` must call
        ``_bootstrap_brain_stack`` so the brain stack is wired
        before any task can submit."""
        from core.orchestrator.main_orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()
        with patch(
            "core.orchestrator.main_orchestrator._bootstrap_brain_stack"
        ) as mock_boot:
            try:
                orchestrator.initialize()
            except Exception:
                # Other init paths may fail in test env; the
                # bootstrap call should still have happened.
                pass
        mock_boot.assert_called()

    def test_handlers_attached_post_initialize(self):
        """End-to-end: post-initialize() the hooks are present."""
        from core.orchestrator.main_orchestrator import MainOrchestrator
        from core.goals import goal_feedback as gf
        from core.hooks import dispatcher as hd

        orchestrator = MainOrchestrator()
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=MagicMock(),
        ):
            try:
                orchestrator.initialize()
            except Exception:
                pass
            assert gf._REGISTERED is True
            assert "approval.executed" in hd._HANDLERS
