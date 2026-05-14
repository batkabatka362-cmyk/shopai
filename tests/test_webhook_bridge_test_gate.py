"""Test that the WebhookFeedbackBridge's Pattern J gate actually
short-circuits the learning fan-out under pytest.

Pre-PR, the bridge's ``_learn`` method called ``LearningLoop.learn``
unconditionally. The existing test file mocked the loop explicitly,
which kept residue out of dev DBs — but only because every test
remembered to mock it. A future test that exercised the bridge end-
to-end without mocking would pollute brain_memory + memory_intel +
data_arch.

This file verifies the defense-in-depth gate: any test that DOESN'T
explicitly disable the gate gets a no-op ``_learn``, even if it
hits the bridge with a real LearningLoop instance.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _seed_executed(queue, *, code: str):
    action = queue.enqueue(
        engine="cart_recovery", action_type="mint_code",
        capability="X", params={}, narrative="",
    )
    queue.approve(action.id, decided_by="op")
    queue.attach_result(
        action.id, success=True, result={"code": code},
    )
    return action


class TestGateActiveByDefault:

    def test_learn_short_circuits_under_pytest(self, isolated_queue):
        """Without disabling the gate, _learn returns False even
        when a working loop is wired."""
        from core.feedback import webhook_bridge as wb

        wb._INSTANCE = None
        bridge = wb.WebhookFeedbackBridge()

        # Real-shape loop: would log if called
        mock_loop = MagicMock()
        bridge._learning_loop = mock_loop

        # Seed a matchable action
        a = _seed_executed(isolated_queue, code="RECOVER-X1")

        report = bridge.handle_event(
            "orders/create",
            {"id": "order_1",
             "discount_codes": [{"code": "RECOVER-X1"}]},
        )

        # Match worked (bridge found the action)
        assert report["status"] == "matched"
        # But LearningLoop.learn was NEVER called — gate fired
        mock_loop.learn.assert_not_called()
        # And feedback_recorded reflects no-op
        assert report["feedback_recorded"] is False

    def test_orphan_path_also_gated(self, isolated_queue):
        """The orphan branch also calls _learn; the gate applies
        symmetrically there."""
        from core.feedback import webhook_bridge as wb

        wb._INSTANCE = None
        bridge = wb.WebhookFeedbackBridge()
        mock_loop = MagicMock()
        bridge._learning_loop = mock_loop

        bridge.handle_event(
            "orders/create",
            {"id": "order_1",
             "discount_codes": [{"code": "UNKNOWN"}]},
        )
        mock_loop.learn.assert_not_called()


class TestGateBypassEnablesLearn:

    def test_disabling_gate_re_enables_learn(
        self, isolated_queue, monkeypatch,
    ):
        """Tests that need to verify learning behavior monkeypatch
        ``_is_test_environment`` to return False — the same
        pattern used by test_webhook_feedback_bridge."""
        monkeypatch.setattr(
            "core.feedback.webhook_bridge._is_test_environment",
            lambda: False,
        )
        from core.feedback import webhook_bridge as wb

        wb._INSTANCE = None
        bridge = wb.WebhookFeedbackBridge()
        mock_loop = MagicMock()
        bridge._learning_loop = mock_loop

        _seed_executed(isolated_queue, code="RECOVER-X1")
        bridge.handle_event(
            "orders/create",
            {"id": "order_1",
             "discount_codes": [{"code": "RECOVER-X1"}]},
        )
        # Now the gate is OFF; learn fires
        mock_loop.learn.assert_called_once()
