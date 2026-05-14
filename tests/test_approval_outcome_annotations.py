"""Tests for the outcome-annotation layer on ApprovalQueue +
WebhookFeedbackBridge.

The webhook bridge (audit #5) already matched Shopify webhook
events back to executed actions and fed LearningLoop. But the
queue itself had no record of redemptions — an operator viewing
``shopai approvals show <action_id>`` for an executed mint
couldn't see "this drove $X in revenue". This file covers the
new bridge → queue annotation path.

Coverage:
  - ApprovalQueue.record_outcome happy path / no-op cases
  - ApprovalQueue.get_outcomes returns the annotation list
  - WebhookFeedbackBridge._feed_matched calls record_outcome
  - Bridge failure (queue unavailable, record_outcome raises)
    surfaces as graceful no-op
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


def _seed_executed(isolated_queue, *, code: str, engine: str = "cart_recovery"):
    action = isolated_queue.enqueue(
        engine=engine, action_type="mint_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params={"token": "c1"}, narrative="",
    )
    isolated_queue.approve(action.id, decided_by="op")
    isolated_queue.attach_result(
        action.id, success=True, result={"code": code},
    )
    return action


# ─── ApprovalQueue.record_outcome ────────────────────────────────


class TestRecordOutcome:

    def test_records_for_known_action(self, isolated_queue):
        a = _seed_executed(isolated_queue, code="X1")
        ok = isolated_queue.record_outcome(
            a.id, topic="orders/create",
            polarity="positive",
            metrics={"revenue": 42.5},
            source_event="order_999",
        )
        assert ok is True

        outcomes = isolated_queue.get_outcomes(a.id)
        assert len(outcomes) == 1
        assert outcomes[0]["topic"] == "orders/create"
        assert outcomes[0]["polarity"] == "positive"
        assert outcomes[0]["metrics"] == {"revenue": 42.5}
        assert outcomes[0]["source_event"] == "order_999"
        assert outcomes[0]["recorded_at"] > 0

    def test_no_op_for_unknown_action(self, isolated_queue):
        ok = isolated_queue.record_outcome(
            "appr_does_not_exist", topic="orders/create",
        )
        assert ok is False
        assert isolated_queue.get_outcomes("appr_does_not_exist") == []

    def test_empty_action_id_rejected(self, isolated_queue):
        assert isolated_queue.record_outcome(
            "", topic="orders/create",
        ) is False

    def test_empty_topic_rejected(self, isolated_queue):
        a = _seed_executed(isolated_queue, code="X1")
        assert isolated_queue.record_outcome(a.id, topic="") is False

    def test_polarity_validation(self, isolated_queue):
        """Unknown polarity coerces to 'neutral' — doesn't reject."""
        a = _seed_executed(isolated_queue, code="X1")
        ok = isolated_queue.record_outcome(
            a.id, topic="x", polarity="invalid_value",
        )
        assert ok is True
        outcomes = isolated_queue.get_outcomes(a.id)
        assert outcomes[0]["polarity"] == "neutral"

    def test_multiple_outcomes_append(self, isolated_queue):
        """A single mint can have many redemptions — outcomes append."""
        a = _seed_executed(isolated_queue, code="X1")
        for i in range(3):
            isolated_queue.record_outcome(
                a.id, topic="orders/create",
                polarity="positive",
                metrics={"order_n": i},
            )
        outcomes = isolated_queue.get_outcomes(a.id)
        assert len(outcomes) == 3
        # Oldest-first ordering preserved
        assert [o["metrics"]["order_n"] for o in outcomes] == [0, 1, 2]

    def test_outcomes_isolated_per_action(self, isolated_queue):
        a1 = _seed_executed(isolated_queue, code="X1")
        a2 = _seed_executed(isolated_queue, code="X2")
        isolated_queue.record_outcome(
            a1.id, topic="orders/create", polarity="positive",
        )
        isolated_queue.record_outcome(
            a2.id, topic="refunds/create", polarity="negative",
        )
        assert len(isolated_queue.get_outcomes(a1.id)) == 1
        assert isolated_queue.get_outcomes(a1.id)[0]["topic"] == "orders/create"
        assert isolated_queue.get_outcomes(a2.id)[0]["topic"] == "refunds/create"


# ─── webhook bridge wiring ────────────────────────────────────────


@pytest.fixture
def fresh_bridge(isolated_queue):
    from core.feedback import webhook_bridge as wb
    wb._INSTANCE = None
    bridge = wb.WebhookFeedbackBridge()
    # Stub LearningLoop so the bridge's feedback fan-out is no-op
    bridge._learning_loop = MagicMock()
    bridge._learning_loop.learn = MagicMock()
    yield bridge


class TestBridgeAnnotation:

    def test_matched_event_annotates_action(
        self, isolated_queue, fresh_bridge,
    ):
        a = _seed_executed(isolated_queue, code="RECOVER-X1")
        report = fresh_bridge.handle_event(
            "orders/create",
            {
                "id": "order_42",
                "discount_codes": [{"code": "RECOVER-X1"}],
                "total_price": "19.99",
            },
        )
        assert report["status"] == "matched"
        assert report["outcome_annotated"] is True

        outcomes = isolated_queue.get_outcomes(a.id)
        assert len(outcomes) == 1
        assert outcomes[0]["topic"] == "orders/create"
        assert outcomes[0]["polarity"] == "positive"
        # source_event from order id
        assert outcomes[0]["source_event"] == "order_42"

    def test_orphan_event_no_annotation(
        self, isolated_queue, fresh_bridge,
    ):
        """Webhook with no matching action → no queue annotation."""
        report = fresh_bridge.handle_event(
            "orders/create",
            {"id": "x", "discount_codes": [{"code": "UNKNOWN"}]},
        )
        assert report["status"] == "orphan"
        # No outcome rows inserted anywhere
        assert isolated_queue.list_executed() == []  # sanity

    def test_negative_polarity_propagated(
        self, isolated_queue, fresh_bridge,
    ):
        a = _seed_executed(isolated_queue, code="RECOVER-X1")
        fresh_bridge.handle_event(
            "refunds/create",
            {"id": "ref_1", "order": {
                "discount_codes": [{"code": "RECOVER-X1"}],
            }},
        )
        outcomes = isolated_queue.get_outcomes(a.id)
        assert len(outcomes) == 1
        assert outcomes[0]["polarity"] == "negative"
        assert outcomes[0]["topic"] == "refunds/create"

    def test_queue_record_failure_graceful(
        self, isolated_queue, fresh_bridge,
    ):
        """record_outcome raising must not crash the bridge."""
        from unittest.mock import patch

        a = _seed_executed(isolated_queue, code="RECOVER-X1")
        with patch.object(
            isolated_queue, "record_outcome",
            side_effect=RuntimeError("db locked"),
        ):
            report = fresh_bridge.handle_event(
                "orders/create",
                {"id": "x",
                 "discount_codes": [{"code": "RECOVER-X1"}]},
            )
        # Still reports matched (LearningLoop side worked)
        assert report["status"] == "matched"
        assert report["outcome_annotated"] is False

    def test_record_outcome_no_action_id_graceful(
        self, isolated_queue, fresh_bridge,
    ):
        """If somehow the matched action dict lacks an id, the
        annotation step short-circuits — no crash."""
        # Direct call to the internal helper with empty action_id
        ok = fresh_bridge._record_queue_outcome(
            action_id="",
            topic="orders/create",
            polarity="positive",
            metrics={},
            payload={"id": "x"},
        )
        assert ok is False
