"""Tests for the autonomous controller's active-store context
wrap on ``run_cycle``.

The controller sets ``active_store(sid)`` before running the
inner cycle body so every ``enqueue`` / ``record_writeback``
during the cycle auto-tags ``store_id=sid``. This is the
production trigger that makes ``shopai transfer suggest`` work
across a fleet -- once the autonomous loop runs once per store,
its actions are tagged automatically.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.context import active_store, get_active_store_id


@pytest.fixture
def controller():
    """Build a minimal AutonomousController with a fake store
    manager so ``run_cycle`` resolves an active store without
    needing real ShopAI infrastructure."""
    from core.autonomous.controller import AutonomousController

    sm = MagicMock()
    sm.active_store_id = "fallback-store"

    # Construct without invoking the heavy default __init__
    # behavior (we don't need the full brain stack for this test).
    c = AutonomousController.__new__(AutonomousController)
    c._store_manager = sm
    c._cycle_count = 0
    return c


# ─── Wrapper sets context for the cycle body ─────────────────


class TestRunCycleSetsContext:

    def test_inner_body_sees_active_store(self, controller):
        observed: dict = {}

        def _fake_inner(sid):
            observed["sid"] = sid
            observed["active"] = get_active_store_id()
            return {"status": "ok", "store_id": sid}

        with patch.object(
            controller, "_run_cycle_internal",
            side_effect=_fake_inner,
        ):
            result = controller.run_cycle(store_id="store-a")

        # The inner body received the resolved sid as its arg
        assert observed["sid"] == "store-a"
        # AND the active-store context was set when it ran
        assert observed["active"] == "store-a"
        # The cycle returned the inner body's return value
        assert result["store_id"] == "store-a"

    def test_context_cleared_after_cycle(self, controller):
        with patch.object(
            controller, "_run_cycle_internal",
            return_value={"status": "ok"},
        ):
            controller.run_cycle(store_id="store-a")
        # Outside the wrapped cycle, the context is back to its
        # prior value (None on a clean thread).
        assert get_active_store_id() is None

    def test_uses_active_store_manager_when_no_arg(self, controller):
        observed: dict = {}

        def _fake_inner(sid):
            observed["sid"] = sid
            return {"status": "ok"}

        with patch.object(
            controller, "_run_cycle_internal",
            side_effect=_fake_inner,
        ):
            # No store_id passed → falls back to store manager
            controller.run_cycle()
        # ``controller.fixture`` sets sm.active_store_id =
        # "fallback-store"
        assert observed["sid"] == "fallback-store"

    def test_no_store_returns_early(self, controller):
        controller._store_manager.active_store_id = ""
        with patch.object(
            controller, "_run_cycle_internal",
        ) as inner:
            result = controller.run_cycle(store_id="")
        # Early return -- inner body never invoked
        inner.assert_not_called()
        assert result.get("status") == "error"

    def test_nested_context_preserved(self, controller):
        """If a caller already has an active_store set (e.g. an
        outer iteration), run_cycle's wrap should restore it on
        exit rather than wiping it."""
        with active_store("outer"):
            with patch.object(
                controller, "_run_cycle_internal",
                return_value={"status": "ok"},
            ):
                controller.run_cycle(store_id="inner")
            # After run_cycle returns, the outer context is
            # restored (not cleared to None).
            assert get_active_store_id() == "outer"


# ─── Cycle body raises -- context still cleared ──────────────


class TestContextResilience:

    def test_inner_raise_does_not_leak_context(self, controller):
        with patch.object(
            controller, "_run_cycle_internal",
            side_effect=RuntimeError("cycle exploded"),
        ):
            with pytest.raises(RuntimeError):
                controller.run_cycle(store_id="store-a")
        # Even when the inner body raises, the active_store
        # context manager's finally clause restores the previous
        # value -- so subsequent calls don't see stale context.
        assert get_active_store_id() is None
