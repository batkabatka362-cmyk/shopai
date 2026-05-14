"""Tests for ``core.feedback.webhook_bridge.WebhookFeedbackBridge``.

Audit #5 — Webhook Feedback Loop. Coverage:

  1. Discount-code extraction handles every Shopify payload shape:
     ``discount_codes: [{code, ...}]`` (current),
     ``discount_codes: ["ABC"]`` (legacy list),
     ``discount_code: "ABC"`` (legacy single-string),
     refund payloads with the order nested under ``order``.
  2. Polarity mapping — orders/create+paid → positive,
     orders/cancelled + refunds/create → negative, anything else
     neutral.
  3. Matched-action path — webhook code matches an EXECUTED
     action's ``result.code``; LearningLoop is fed with the
     ENGINE that minted the code, not a generic category.
  4. Orphan path — no matching code; LearningLoop still gets
     a ``market_signals`` entry.
  5. Failure resilience — LearningLoop unavailable, queue
     unavailable, malformed payload all surface graceful no-ops
     without raising.
  6. Stats counter increments per code path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def fresh_bridge(isolated_queue):
    """A bridge whose singletons are freshly resolved against
    the isolated queue and a stubbed LearningLoop."""
    from core.feedback import webhook_bridge as wb
    wb._INSTANCE = None
    bridge = wb.WebhookFeedbackBridge()
    yield bridge


def _enqueue_executed_minted_code(
    isolated_queue, *, engine: str, code: str, action_type: str = "mint_loyalty_code",
):
    """Helper: park a minted code as an EXECUTED action so the
    bridge has something to match against."""
    action = isolated_queue.enqueue(
        engine=engine,
        action_type=action_type,
        capability="SHOPIFY_CREATE_DISCOUNT",
        params={"customer_id": "c1", "percentage": 10.0},
        narrative="VIP reward",
    )
    isolated_queue.approve(action.id, decided_by="op")
    isolated_queue.attach_result(
        action.id, success=True,
        result={"code": code, "discount_id": "1", "ends_at": "2099-01-01"},
    )
    return action.id


# ─── discount code extraction ───────────────────────────────────


class TestDiscountCodeExtraction:

    @pytest.mark.parametrize("payload, expected", [
        ({"discount_codes": [{"code": "ABC"}]}, ["ABC"]),
        ({"discount_codes": [{"code": "X"}, {"code": "Y"}]}, ["X", "Y"]),
        ({"discount_codes": ["RAW"]}, ["RAW"]),
        ({"discount_code": "LEGACY"}, ["LEGACY"]),
        ({"discount_codes": [{"code": "A"}], "discount_code": "B"},
         ["A", "B"]),
        # Refund: nested order
        ({"order": {"discount_codes": [{"code": "REF"}]}}, ["REF"]),
        # Empty / missing
        ({}, []),
        ({"discount_codes": []}, []),
        ({"discount_codes": [{"code": ""}]}, []),
    ])
    def test_extracts_codes(self, payload, expected):
        from core.feedback.webhook_bridge import _extract_discount_codes
        assert _extract_discount_codes(payload) == expected


# ─── polarity ──────────────────────────────────────────────────


class TestPolarity:

    @pytest.mark.parametrize("topic, expected", [
        ("orders/create", "positive"),
        ("orders/paid", "positive"),
        ("orders/cancelled", "negative"),
        ("refunds/create", "negative"),
        ("products/update", "neutral"),
        ("checkouts/create", "neutral"),
    ])
    def test_polarity_mapping(self, topic, expected, fresh_bridge):
        assert fresh_bridge._polarity(topic) == expected


# ─── matched-action path ───────────────────────────────────────


class TestMatchedAction:

    def test_order_with_minted_code_feeds_engine_specific_signal(
        self, fresh_bridge, isolated_queue,
    ):
        _enqueue_executed_minted_code(
            isolated_queue, engine="loyalty", code="LOYALTY-X-42",
        )

        mock_loop = MagicMock()
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=mock_loop,
        ):
            result = fresh_bridge.handle_event(
                "orders/create",
                {
                    "id": "o1",
                    "total_price": "75.00",
                    "discount_codes": [{"code": "LOYALTY-X-42"}],
                    "created_at": "2026-04-27T12:00:00Z",
                },
            )

        assert result["status"] == "matched"
        assert result["engine"] == "loyalty"
        assert result["polarity"] == "positive"
        assert result["feedback_recorded"] is True

        # LearningLoop got the engine-specific category, not the
        # generic market_signals fallback.
        assert mock_loop.learn.called
        kw = mock_loop.learn.call_args.kwargs
        assert kw["category"] == "loyalty"
        assert kw["metrics"]["profit"] == 75.0
        assert kw["metrics"]["conversion"] == 1.0

    def test_refund_with_minted_code_feeds_negative_signal(
        self, fresh_bridge, isolated_queue,
    ):
        _enqueue_executed_minted_code(
            isolated_queue, engine="discount_strategy", code="PROMO-15",
            action_type="mint_strategy_code",
        )

        mock_loop = MagicMock()
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=mock_loop,
        ):
            result = fresh_bridge.handle_event(
                "refunds/create",
                {
                    "amount": "25.00",
                    "order": {"discount_codes": [{"code": "PROMO-15"}]},
                },
            )

        assert result["status"] == "matched"
        assert result["engine"] == "discount_strategy"
        assert result["polarity"] == "negative"
        kw = mock_loop.learn.call_args.kwargs
        # Negative → profit goes NEGATIVE, conversion stays 0.
        assert kw["metrics"]["profit"] == -25.0
        assert kw["metrics"]["conversion"] == 0.0

    def test_match_is_case_insensitive(
        self, fresh_bridge, isolated_queue,
    ):
        _enqueue_executed_minted_code(
            isolated_queue, engine="loyalty", code="loyalty-x-42",
        )

        mock_loop = MagicMock()
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=mock_loop,
        ):
            result = fresh_bridge.handle_event(
                "orders/create",
                {
                    "total_price": "50",
                    "discount_codes": [{"code": "LOYALTY-X-42"}],
                },
            )
        assert result["status"] == "matched"


# ─── orphan path ───────────────────────────────────────────────


class TestOrphanEvents:

    def test_order_without_code_falls_to_market_signals(
        self, fresh_bridge, isolated_queue,
    ):
        mock_loop = MagicMock()
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=mock_loop,
        ):
            result = fresh_bridge.handle_event(
                "orders/create",
                {"id": "o1", "total_price": "30"},
            )

        assert result["status"] == "orphan"
        assert result["polarity"] == "positive"
        kw = mock_loop.learn.call_args.kwargs
        assert kw["category"] == "market_signals"
        assert kw["action"] == "orders/create"
        assert kw["metrics"]["profit"] == 30.0

    def test_unknown_code_in_payload_falls_to_orphan(
        self, fresh_bridge, isolated_queue,
    ):
        # Code present but no executed action ever minted it.
        mock_loop = MagicMock()
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=mock_loop,
        ):
            result = fresh_bridge.handle_event(
                "orders/create",
                {"discount_codes": [{"code": "EXTERNAL-CODE"}],
                 "total_price": "20"},
            )
        assert result["status"] == "orphan"
        assert mock_loop.learn.call_args.kwargs["category"] == "market_signals"


# ─── failure resilience ────────────────────────────────────────


class TestFailureResilience:

    def test_missing_topic_no_op(self, fresh_bridge):
        result = fresh_bridge.handle_event("", {"total_price": "10"})
        assert result["status"] == "noop"
        assert result["reason"] == "missing_topic"

    def test_non_dict_payload_treated_as_empty(self, fresh_bridge):
        # bridge coerces non-dict to {} and proceeds as orphan.
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=MagicMock(),
        ):
            result = fresh_bridge.handle_event("orders/create", "garbage")
        assert result["status"] == "orphan"

    def test_learning_loop_unavailable_no_op(self, fresh_bridge):
        with patch(
            "core.brain.learning_loop.LearningLoop",
            side_effect=ImportError("missing dep"),
        ):
            result = fresh_bridge.handle_event(
                "orders/create", {"total_price": "10"},
            )
        # Still returns a structured result; feedback_recorded=False.
        assert result["status"] in {"orphan", "matched"}
        assert result["feedback_recorded"] is False

    def test_learning_loop_raises_caught(self, fresh_bridge):
        bad_loop = MagicMock()
        bad_loop.learn.side_effect = RuntimeError("DB locked")
        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=bad_loop,
        ):
            result = fresh_bridge.handle_event(
                "orders/create", {"total_price": "10"},
            )
        assert result["status"] == "orphan"
        assert result["feedback_recorded"] is False

    def test_internal_exception_returns_error_dict(
        self, fresh_bridge,
    ):
        with patch(
            "core.feedback.webhook_bridge._extract_discount_codes",
            side_effect=RuntimeError("bang"),
        ):
            result = fresh_bridge.handle_event(
                "orders/create", {"total_price": "10"},
            )
        assert result["status"] == "error"
        assert "bang" in result["error"]


# ─── stats counter ─────────────────────────────────────────────


class TestStats:

    def test_counters_increment_per_path(
        self, fresh_bridge, isolated_queue,
    ):
        _enqueue_executed_minted_code(
            isolated_queue, engine="loyalty", code="LOY",
        )

        with patch(
            "core.brain.learning_loop.LearningLoop",
            return_value=MagicMock(),
        ):
            fresh_bridge.handle_event(
                "orders/create",
                {"discount_codes": [{"code": "LOY"}],
                 "total_price": "1"},
            )
            fresh_bridge.handle_event(
                "orders/create", {"total_price": "2"},
            )
            fresh_bridge.handle_event("", {})

        stats = fresh_bridge.get_stats()
        assert stats["events_seen"] == 3
        assert stats["matched_actions"] == 1
        assert stats["orphan_events"] == 1
        assert stats["feedback_recorded"] >= 2
