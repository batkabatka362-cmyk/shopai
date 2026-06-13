"""W963-133: approval executor wraps dispatcher in
active_store(action.store_id).

Closes the third entry point where per-store substrate
was dormant pre-fix:
  - Autonomous cycle (W963-127): wrapped engine.run
  - Webhook handler (W963-128): wrapped per webhook shop
  - Approval executor (W963-133, this commit): wraps
    dispatcher per approved action

Every approved action that previously fired with the
env-default Shopify credentials now resolves the action's
own per-store credentials.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestExecutorActiveStoreWrap:
    def test_dispatcher_invoked_inside_active_store(
        self, monkeypatch,
    ):
        """When the action has a store_id, the dispatcher
        is called inside active_store(store_id)."""
        from core.context import get_active_store_id
        from core.approval import executor as ex
        from core.approval.queue import (
            ApprovalAction, ApprovalStatus,
        )

        captured: dict = {"sid": None}

        def fake_dispatcher(params):
            captured["sid"] = (
                get_active_store_id() or ""
            )
            return True, {"ok": True}

        # Build a fake action with store_id
        fake_action = ApprovalAction(
            id="act_w963_133_1",
            engine="loyalty",
            action_type="mint_loyalty_code_test",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"x": 1},
            narrative="test",
            confidence=0.9,
            status=ApprovalStatus.APPROVED,
            proposed_at=0.0,
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
            store_id="store_a",
        )
        fake_queue = MagicMock()
        fake_queue.get.return_value = fake_action
        fake_queue.attach_result.return_value = fake_action

        with patch.dict(
            ex._DISPATCHERS,
            {"mint_loyalty_code_test": fake_dispatcher},
            clear=False,
        ), patch.object(
            ex, "get_approval_queue",
            return_value=fake_queue,
        ), patch.object(
            ex, "_ensure_dispatchers_loaded",
        ), patch.object(
            ex, "_record_outcome",
        ):
            ex.execute_action("act_w963_133_1")

        # Dispatcher saw the right active_store
        assert captured["sid"] == "store_a"

    def test_no_store_id_no_wrap(self, monkeypatch):
        """When the action has no store_id (legacy
        fleet-level action), the dispatcher fires
        without a wrap (no crash)."""
        from core.context import get_active_store_id
        from core.approval import executor as ex
        from core.approval.queue import (
            ApprovalAction, ApprovalStatus,
        )

        captured: dict = {"sid": "(unset)"}

        def fake_dispatcher(params):
            captured["sid"] = (
                get_active_store_id() or ""
            )
            return True, {"ok": True}

        fake_action = ApprovalAction(
            id="act_w963_133_2",
            engine="fleet_op",
            action_type="fleet_op_test",
            capability="FLEET_OP",
            params={},
            narrative="test",
            confidence=0.9,
            status=ApprovalStatus.APPROVED,
            proposed_at=0.0,
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
            store_id=None,
        )
        fake_queue = MagicMock()
        fake_queue.get.return_value = fake_action
        fake_queue.attach_result.return_value = fake_action

        with patch.dict(
            ex._DISPATCHERS,
            {"fleet_op_test": fake_dispatcher},
            clear=False,
        ), patch.object(
            ex, "get_approval_queue",
            return_value=fake_queue,
        ), patch.object(
            ex, "_ensure_dispatchers_loaded",
        ), patch.object(
            ex, "_record_outcome",
        ):
            ex.execute_action("act_w963_133_2")

        # No wrap fired -- captured is whatever was
        # already in thread-local (typically None/"")
        assert captured["sid"] in ("", "main", None)

    def test_dispatcher_exception_still_recorded(
        self, monkeypatch,
    ):
        """Dispatcher raising under active_store wrap
        must still be caught + recorded as failure."""
        from core.approval import executor as ex
        from core.approval.queue import (
            ApprovalAction, ApprovalStatus,
        )

        def fake_dispatcher(params):
            raise RuntimeError("test: dispatcher failure")

        fake_action = ApprovalAction(
            id="act_w963_133_3",
            engine="x",
            action_type="x_test_raise",
            capability="X",
            params={},
            narrative="test",
            confidence=0.9,
            status=ApprovalStatus.APPROVED,
            proposed_at=0.0,
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
            store_id="store_a",
        )
        fake_queue = MagicMock()
        fake_queue.get.return_value = fake_action
        fake_queue.attach_result.return_value = fake_action

        with patch.dict(
            ex._DISPATCHERS,
            {"x_test_raise": fake_dispatcher},
            clear=False,
        ), patch.object(
            ex, "get_approval_queue",
            return_value=fake_queue,
        ), patch.object(
            ex, "_ensure_dispatchers_loaded",
        ), patch.object(
            ex, "_record_outcome",
        ):
            ex.execute_action("act_w963_133_3")

        # attach_result called with success=False
        fake_queue.attach_result.assert_called_once()
        kwargs = fake_queue.attach_result.call_args.kwargs
        assert kwargs["success"] is False
