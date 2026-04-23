"""Unit + integration tests for core/system/approval_queue.py."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.contracts import RiskLevel
from core.system.approval_queue import (
    ApprovalQueue,
    ApprovalRequest,
    get_queue,
    reset_singleton_for_tests,
)


@pytest.fixture
def queue(tmp_path):
    return ApprovalQueue(db_path=str(tmp_path / "aq.db"))


# ── enqueue ──────────────────────────────────────────────


class TestEnqueue:
    def test_basic_enqueue(self, queue):
        req = queue.enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20.0},
            RiskLevel.HIGH,
        )
        assert req.request_id
        assert len(req.request_id) == 16
        assert req.action_type == "ad_campaign_create"
        assert req.status == "pending"
        assert req.payload["daily_budget_usd"] == 20.0
        assert req.risk_level is RiskLevel.HIGH

    def test_expires_at_is_in_future(self, queue):
        now = time.time()
        req = queue.enqueue(
            "product_delete", {}, RiskLevel.HIGH,
        )
        assert req.expires_at > now
        # Default 30 min TTL → expires_at - requested_at ≈ 1800s
        assert 1500 < (req.expires_at - req.requested_at) < 2100

    def test_custom_ttl(self, queue):
        req = queue.enqueue(
            "x", {}, RiskLevel.HIGH, ttl_minutes=60,
        )
        delta = req.expires_at - req.requested_at
        assert 3400 < delta < 3700

    def test_blank_action_type_raises(self, queue):
        with pytest.raises(ValueError, match="action_type"):
            queue.enqueue("", {}, RiskLevel.HIGH)

    def test_unique_request_ids(self, queue):
        ids = {
            queue.enqueue("x", {}, RiskLevel.HIGH).request_id
            for _ in range(20)
        }
        assert len(ids) == 20  # all unique

    def test_payload_persists(self, queue):
        payload = {
            "store": "deguar",
            "nested": {"budget": 42.5, "list": [1, 2, 3]},
        }
        req = queue.enqueue(
            "ad_budget_set", payload, RiskLevel.CRITICAL,
        )
        fetched = queue.get(req.request_id)
        assert fetched.payload == payload


# ── approve / deny ──────────────────────────────────────


class TestApproveAndDeny:
    def test_approve_transitions_to_approved(self, queue):
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        result = queue.approve(
            req.request_id, owner_id="dega",
            reason="looks good",
        )
        assert result.status == "approved"
        assert result.decided_by == "dega"
        assert result.decision_reason == "looks good"
        assert result.decided_at > 0

    def test_deny_transitions_to_denied(self, queue):
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        result = queue.deny(
            req.request_id, reason="budget too high",
        )
        assert result.status == "denied"
        assert result.decision_reason == "budget too high"

    def test_approve_unknown_id_returns_none(self, queue):
        assert queue.approve("does-not-exist") is None

    def test_approve_is_idempotent(self, queue):
        """Double-approve is a no-op — returns existing row
        untouched (important for flaky Telegram webhooks)."""
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        first = queue.approve(req.request_id, owner_id="dega")
        # Try to re-approve with different owner/reason — must
        # NOT overwrite
        second = queue.approve(
            req.request_id, owner_id="other",
            reason="different",
        )
        assert second.decided_by == "dega"
        assert second.decision_reason == ""

    def test_cannot_deny_after_approve(self, queue):
        """Terminal state is sticky — denying an approved
        request returns the approved row unchanged."""
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        queue.approve(req.request_id, owner_id="dega")
        result = queue.deny(req.request_id, reason="flip")
        assert result.status == "approved"
        assert result.decision_reason != "flip"

    def test_expired_ttl_denies_decision(self, tmp_path):
        """If the caller tries to approve AFTER the TTL
        elapsed, the row should auto-expire + return expired
        (rather than silently approve a stale request)."""
        clock = {"t": 1_000_000.0}
        q = ApprovalQueue(
            db_path=str(tmp_path / "q.db"),
            now_fn=lambda: clock["t"],
        )
        req = q.enqueue("x", {}, RiskLevel.HIGH, ttl_minutes=5)
        # Jump 10 min into the future
        clock["t"] = 1_000_000.0 + 600
        result = q.approve(req.request_id)
        assert result.status == "expired"


# ── pending / recent / stats ─────────────────────────────


class TestReadSurface:
    def test_pending_fifo_order(self, queue):
        """Oldest enqueue first — owner processes in arrival
        order."""
        ids = []
        for i in range(3):
            req = queue.enqueue(f"a{i}", {}, RiskLevel.HIGH)
            ids.append(req.request_id)
            time.sleep(0.01)  # enforce distinct requested_at
        pending = queue.pending()
        assert [r.request_id for r in pending] == ids

    def test_approved_not_in_pending(self, queue):
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        queue.enqueue("y", {}, RiskLevel.HIGH)
        queue.approve(req.request_id)
        pending = queue.pending()
        assert len(pending) == 1
        assert all(r.status == "pending" for r in pending)

    def test_recent_newest_first(self, queue):
        ids = []
        for i in range(3):
            req = queue.enqueue(f"a{i}", {}, RiskLevel.HIGH)
            ids.append(req.request_id)
            time.sleep(0.01)
        recent = queue.recent()
        # Reversed — newest first
        assert [r.request_id for r in recent] == list(reversed(ids))

    def test_stats_shape(self, queue):
        queue.enqueue("x", {}, RiskLevel.HIGH)
        req2 = queue.enqueue("y", {}, RiskLevel.HIGH)
        req3 = queue.enqueue("z", {}, RiskLevel.HIGH)
        queue.approve(req2.request_id)
        queue.deny(req3.request_id)
        s = queue.stats()
        assert s["pending"] == 1
        assert s["approved"] == 1
        assert s["denied"] == 1
        assert s["expired"] == 0
        assert s["total"] == 3

    def test_recent_limit_caps(self, queue):
        for i in range(100):
            queue.enqueue(f"a{i}", {}, RiskLevel.HIGH)
        assert len(queue.recent(limit=20)) == 20


# ── expire_old ─────────────────────────────────────────


class TestExpireOld:
    def test_sweeps_expired_pending(self, tmp_path):
        clock = {"t": 1_000_000.0}
        q = ApprovalQueue(
            db_path=str(tmp_path / "q.db"),
            now_fn=lambda: clock["t"],
        )
        q.enqueue("x", {}, RiskLevel.HIGH, ttl_minutes=5)
        q.enqueue("y", {}, RiskLevel.HIGH, ttl_minutes=60)
        # Jump 10 min
        clock["t"] = 1_000_000.0 + 600
        n = q.expire_old()
        assert n == 1  # only the 5-min one
        assert q.stats()["expired"] == 1
        assert q.stats()["pending"] == 1

    def test_empty_queue_returns_zero(self, queue):
        assert queue.expire_old() == 0


# ── Persistence across processes ────────────────────────


class TestPersistence:
    def test_survives_reopen(self, tmp_path):
        path = str(tmp_path / "persist.db")
        q1 = ApprovalQueue(db_path=path)
        req = q1.enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            RiskLevel.HIGH,
        )
        # New instance on same path
        q2 = ApprovalQueue(db_path=path)
        fetched = q2.get(req.request_id)
        assert fetched is not None
        assert fetched.action_type == "ad_campaign_create"
        assert fetched.payload["daily_budget_usd"] == 20


# ── ApprovalRequest.as_dict ────────────────────────────


class TestDataclass:
    def test_as_dict_shape(self, queue):
        req = queue.enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            RiskLevel.HIGH,
        )
        d = req.as_dict()
        assert d["risk_level"] == "high"  # enum .value
        assert d["status"] == "pending"
        assert d["payload"]["daily_budget_usd"] == 20
        assert isinstance(d["requested_at"], float)

    def test_is_terminal(self, queue):
        req = queue.enqueue("x", {}, RiskLevel.HIGH)
        assert not req.is_terminal()
        req.status = "approved"
        assert req.is_terminal()
        req.status = "denied"
        assert req.is_terminal()
        req.status = "expired"
        assert req.is_terminal()


# ── Singleton ─────────────────────────────────────────


class TestSingleton:
    def test_get_queue_returns_same_instance(self, tmp_path):
        reset_singleton_for_tests()
        # Override env so singleton uses tmp path
        q1 = get_queue(str(tmp_path / "sing.db"))
        q2 = get_queue(str(tmp_path / "sing.db"))
        assert q1 is q2
        reset_singleton_for_tests()
