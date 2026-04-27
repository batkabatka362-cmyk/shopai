"""Tests for ``core.approval.queue.ApprovalQueue``.

Coverage:
  1. Schema bootstrap on a fresh DB.
  2. ``enqueue`` — happy path, JSON round-trip of params.
  3. ``list_pending`` — ordering, engine filter, limit.
  4. ``approve`` / ``reject`` — happy path, idempotency on
     already-resolved actions, missing-id behaviour.
  5. ``attach_result`` — only acts on APPROVED actions.
  6. ``stats`` — counts per status.
  7. ``ApprovalStatus`` lifecycle ordering.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.approval.queue import (
    ApprovalQueue,
    ApprovalStatus,
)


@pytest.fixture
def queue(tmp_path: Path) -> ApprovalQueue:
    return ApprovalQueue(db_path=tmp_path / "approval.db")


# ─── enqueue ─────────────────────────────────────────────────────


class TestEnqueue:

    def test_enqueue_returns_pending_action(self, queue: ApprovalQueue):
        action = queue.enqueue(
            engine="discount_strategy",
            action_type="mint_promo_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"value": 15.0, "code": "PROMO-15"},
            narrative="Storewide 15% promo for back-to-school",
            confidence=0.82,
        )
        assert action.id.startswith("appr_")
        assert action.status == ApprovalStatus.PENDING
        assert action.engine == "discount_strategy"
        assert action.action_type == "mint_promo_code"
        assert action.params == {"value": 15.0, "code": "PROMO-15"}
        assert action.confidence == 0.82
        assert action.decided_at is None
        assert action.proposed_at <= time.time()

    def test_params_round_trip_through_json(self, queue: ApprovalQueue):
        action = queue.enqueue(
            engine="loyalty",
            action_type="mint_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"value": 10, "nested": {"reason": "tier reward"}},
        )
        re_fetched = queue.get(action.id)
        assert re_fetched is not None
        assert re_fetched.params == {
            "value": 10, "nested": {"reason": "tier reward"},
        }

    def test_get_returns_none_for_unknown_id(self, queue: ApprovalQueue):
        assert queue.get("appr_does_not_exist") is None


# ─── list_pending ────────────────────────────────────────────────


class TestListPending:

    def test_returns_only_pending_actions(self, queue: ApprovalQueue):
        a1 = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        a2 = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        queue.approve(a1.id, decided_by="op", reason="looks good")

        pending = queue.list_pending()
        ids = [p.id for p in pending]
        assert a2.id in ids
        assert a1.id not in ids  # already approved

    def test_oldest_first_ordering(self, queue: ApprovalQueue):
        first = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        time.sleep(0.005)  # different proposed_at
        second = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        pending = queue.list_pending()
        # Strict order: first, then second.
        assert pending[0].id == first.id
        assert pending[1].id == second.id

    def test_engine_filter(self, queue: ApprovalQueue):
        loyalty = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        discount = queue.enqueue(
            engine="discount_strategy", action_type="mint",
            capability="X", params={},
        )
        out = queue.list_pending(engine="loyalty")
        assert [a.id for a in out] == [loyalty.id]
        out = queue.list_pending(engine="discount_strategy")
        assert [a.id for a in out] == [discount.id]

    def test_limit_caps_page_size(self, queue: ApprovalQueue):
        for _ in range(5):
            queue.enqueue(
                engine="loyalty", action_type="mint", capability="X",
                params={},
            )
        out = queue.list_pending(limit=3)
        assert len(out) == 3


# ─── approve / reject ────────────────────────────────────────────


class TestApproveReject:

    def test_approve_flips_status_and_records_metadata(
        self, queue: ApprovalQueue,
    ):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        out = queue.approve(
            a.id, decided_by="alice", reason="customer is VIP",
        )
        assert out is not None
        assert out.status == ApprovalStatus.APPROVED
        assert out.decided_by == "alice"
        assert out.decision_reason == "customer is VIP"
        assert out.decided_at is not None and out.decided_at >= a.proposed_at

    def test_reject_flips_status_and_records_metadata(
        self, queue: ApprovalQueue,
    ):
        a = queue.enqueue(
            engine="discount_strategy", action_type="mint",
            capability="X", params={},
        )
        out = queue.reject(
            a.id, decided_by="bob", reason="cannibalization risk",
        )
        assert out is not None
        assert out.status == ApprovalStatus.REJECTED
        assert out.decision_reason == "cannibalization risk"

    def test_approve_already_approved_is_noop(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        queue.approve(a.id, decided_by="alice", reason="ok")
        # Second approve must NOT mutate metadata; returns None to
        # signal "no transition happened".
        again = queue.approve(a.id, decided_by="bob", reason="me too")
        assert again is None
        # Original metadata still intact.
        current = queue.get(a.id)
        assert current is not None
        assert current.decided_by == "alice"
        assert current.decision_reason == "ok"

    def test_reject_after_approve_is_noop(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        queue.approve(a.id, decided_by="alice", reason="ok")
        result = queue.reject(a.id, decided_by="bob", reason="never mind")
        assert result is None
        current = queue.get(a.id)
        assert current is not None
        assert current.status == ApprovalStatus.APPROVED

    def test_approve_missing_id(self, queue: ApprovalQueue):
        assert queue.approve("appr_does_not_exist") is None


# ─── attach_result ───────────────────────────────────────────────


class TestAttachResult:

    def test_success_flips_to_executed(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        queue.approve(a.id, decided_by="alice", reason="ok")
        out = queue.attach_result(
            a.id, success=True, result={"shopify_id": "gid://1"},
        )
        assert out is not None
        assert out.status == ApprovalStatus.EXECUTED
        assert out.result == {"shopify_id": "gid://1"}

    def test_failure_flips_to_failed(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        queue.approve(a.id, decided_by="alice", reason="ok")
        out = queue.attach_result(
            a.id, success=False, result={"error": "scope_missing"},
        )
        assert out is not None
        assert out.status == ApprovalStatus.FAILED
        assert out.result == {"error": "scope_missing"}

    def test_attach_to_unapproved_action_is_noop(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        # Still PENDING — attach must refuse.
        result = queue.attach_result(a.id, success=True, result={})
        assert result is None
        current = queue.get(a.id)
        assert current is not None
        assert current.status == ApprovalStatus.PENDING


# ─── stats ───────────────────────────────────────────────────────


class TestStats:

    def test_counts_by_status(self, queue: ApprovalQueue):
        for _ in range(3):
            queue.enqueue(
                engine="x", action_type="y", capability="Z",
                params={},
            )
        first_two = queue.list_pending()[:2]
        queue.approve(first_two[0].id)
        queue.reject(first_two[1].id)
        stats = queue.stats()
        assert stats["pending"] == 1
        assert stats["approved"] == 1
        assert stats["rejected"] == 1
        # Untouched buckets stay at 0.
        assert stats["executed"] == 0
        assert stats["failed"] == 0
        assert stats["expired"] == 0

    def test_empty_queue_returns_all_zeros(self, queue: ApprovalQueue):
        stats = queue.stats()
        assert all(v == 0 for v in stats.values())
        assert set(stats.keys()) >= {
            "pending", "approved", "rejected", "executed", "failed",
        }


# ─── ApprovalAction serialization ────────────────────────────────


class TestSerialization:

    def test_to_dict_round_trip(self, queue: ApprovalQueue):
        a = queue.enqueue(
            engine="discount_strategy",
            action_type="mint_promo_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"value": 20.0},
            narrative="20% storewide",
            confidence=0.91,
        )
        d = a.to_dict()
        assert d["status"] == "pending"
        assert d["engine"] == "discount_strategy"
        assert d["params"] == {"value": 20.0}
        assert d["narrative"] == "20% storewide"
        assert d["confidence"] == 0.91
        assert d["decided_at"] is None
        assert d["result"] is None
