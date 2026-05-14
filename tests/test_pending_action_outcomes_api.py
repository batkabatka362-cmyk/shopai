"""Tests for the ``?include_outcomes=1`` flag on
``GET /api/pending-actions/<id>``.

PR #112 added per-action outcome storage. This PR exposes it on
the existing read endpoint so callers (CLI, future UI, API
consumers) don't need a separate trip to fetch redemption
history for an executed action.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_handler():
    from api.server import ShopAIHandler

    handler = ShopAIHandler.__new__(ShopAIHandler)
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda status, body: responses.append((status, body))
    )
    return handler, responses


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _seed_action_with_outcome(queue, *, code: str = "X1"):
    """Helper: enqueue → approve → execute → record one outcome."""
    a = queue.enqueue(
        engine="cart_recovery", action_type="mint_code",
        capability="X", params={}, narrative="",
    )
    queue.approve(a.id, decided_by="op")
    queue.attach_result(a.id, success=True, result={"code": code})
    queue.record_outcome(
        a.id, topic="orders/create",
        polarity="positive",
        metrics={"revenue": 19.99},
        source_event="order_1",
    )
    return a


# ─── _truthy_param ────────────────────────────────────────────────


class TestTruthyParam:

    def test_recognises_truthy_values(self):
        from api.server import _truthy_param
        for v in ["1", "true", "yes", "on", "TRUE", "Yes"]:
            assert _truthy_param([v]) is True, v

    def test_rejects_falsy_values(self):
        from api.server import _truthy_param
        for v in ["0", "false", "no", "off", "", "anything"]:
            assert _truthy_param([v]) is False, v

    def test_handles_missing(self):
        from api.server import _truthy_param
        assert _truthy_param(None) is False
        assert _truthy_param([]) is False

    def test_accepts_scalar(self):
        from api.server import _truthy_param
        assert _truthy_param("1") is True
        assert _truthy_param("0") is False


# ─── GET /api/pending-actions/<id> ?include_outcomes ──────────────


class TestPendingActionOutcomes:

    def test_default_omits_outcomes(self, isolated_queue):
        a = _seed_action_with_outcome(isolated_queue)
        handler, responses = _make_handler()
        handler._get_pending_action(a.id, {})
        status, body = responses[0]
        assert status == 200
        # No outcomes key when flag is absent
        assert "outcomes" not in body

    def test_flag_includes_outcomes(self, isolated_queue):
        a = _seed_action_with_outcome(isolated_queue)
        handler, responses = _make_handler()
        handler._get_pending_action(
            a.id, {"include_outcomes": ["1"]},
        )
        status, body = responses[0]
        assert status == 200
        assert "outcomes" in body
        assert len(body["outcomes"]) == 1
        assert body["outcomes"][0]["topic"] == "orders/create"
        assert body["outcomes"][0]["metrics"] == {"revenue": 19.99}
        assert body["outcomes"][0]["source_event"] == "order_1"

    def test_no_outcomes_returns_empty_list(self, isolated_queue):
        """Action with no downstream events → empty list, not absent."""
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="X",
            params={}, narrative="",
        )
        handler, responses = _make_handler()
        handler._get_pending_action(
            a.id, {"include_outcomes": ["true"]},
        )
        status, body = responses[0]
        assert status == 200
        assert body["outcomes"] == []

    def test_falsy_flag_omits_outcomes(self, isolated_queue):
        a = _seed_action_with_outcome(isolated_queue)
        handler, responses = _make_handler()
        handler._get_pending_action(
            a.id, {"include_outcomes": ["0"]},
        )
        status, body = responses[0]
        assert status == 200
        assert "outcomes" not in body

    def test_outcomes_lookup_failure_falls_back_to_empty(
        self, isolated_queue,
    ):
        """If the queue's get_outcomes raises, the endpoint should
        still return the action with outcomes=[] — never 500 on
        the read endpoint."""
        from unittest.mock import patch

        a = _seed_action_with_outcome(isolated_queue)
        with patch.object(
            isolated_queue, "get_outcomes",
            side_effect=RuntimeError("db lock"),
        ):
            handler, responses = _make_handler()
            handler._get_pending_action(
                a.id, {"include_outcomes": ["1"]},
            )
        status, body = responses[0]
        assert status == 200
        assert body["outcomes"] == []

    def test_unknown_action_still_404(self, isolated_queue):
        handler, responses = _make_handler()
        handler._get_pending_action(
            "appr_does_not_exist_xyz",
            {"include_outcomes": ["1"]},
        )
        status, body = responses[0]
        assert status == 404
        assert "error" in body

    def test_invalid_id_still_400(self, isolated_queue):
        handler, responses = _make_handler()
        handler._get_pending_action(
            "../bad/id", {"include_outcomes": ["1"]},
        )
        status, body = responses[0]
        assert status == 400

    def test_multiple_outcomes_returned_in_order(
        self, isolated_queue,
    ):
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="X",
            params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        isolated_queue.attach_result(a.id, success=True, result={"code": "X"})
        # Record three outcomes
        for i, topic in enumerate(
            ["orders/create", "orders/paid", "refunds/create"]
        ):
            polarity = (
                "positive" if "create" in topic and "refunds" not in topic
                else "positive" if topic == "orders/paid"
                else "negative"
            )
            isolated_queue.record_outcome(
                a.id, topic=topic, polarity=polarity,
                metrics={"i": i},
            )
        handler, responses = _make_handler()
        handler._get_pending_action(
            a.id, {"include_outcomes": ["1"]},
        )
        status, body = responses[0]
        assert status == 200
        assert len(body["outcomes"]) == 3
        # Oldest-first preserved
        assert body["outcomes"][0]["topic"] == "orders/create"
        assert body["outcomes"][2]["topic"] == "refunds/create"
