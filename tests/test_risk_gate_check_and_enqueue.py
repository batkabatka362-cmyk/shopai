"""Integration tests for risk_gate.check_and_enqueue — the
proceed/queue decision helper wired into callers like
publisher_bundle + campaign_activator."""
from __future__ import annotations

import pytest

from core.contracts import RiskLevel
from core.system import risk_gate
from core.system.approval_queue import ApprovalQueue


@pytest.fixture
def queue(tmp_path):
    return ApprovalQueue(db_path=str(tmp_path / "q.db"))


class TestDryRunShortCircuit:
    def test_dry_run_always_proceeds(self, queue):
        """No money commit in dry-run → always proceed, never
        enqueue. Keeps unit tests + dry-run previews clean."""
        proceed, req_id, level = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 500},  # would be CRITICAL live
            auto_approve=False,
            live_execution=False,
            queue=queue,
        )
        assert proceed is True
        assert req_id == ""
        assert level is RiskLevel.CRITICAL  # still classifies
        # Nothing enqueued
        assert queue.stats()["total"] == 0


class TestAutoApprovedProceeds:
    def test_low_action_proceeds(self, queue):
        proceed, req_id, level = risk_gate.check_and_enqueue(
            "metafield_write", {},
            auto_approve=False,
            live_execution=True,
            queue=queue,
        )
        assert proceed is True
        assert req_id == ""
        assert level is RiskLevel.LOW
        assert queue.stats()["total"] == 0

    def test_medium_with_both_flags_proceeds(self, queue):
        proceed, req_id, _ = risk_gate.check_and_enqueue(
            "product_publish", {},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        assert proceed is True
        assert req_id == ""
        assert queue.stats()["total"] == 0

    def test_medium_without_auto_approve_enqueues(self, queue):
        proceed, req_id, _ = risk_gate.check_and_enqueue(
            "product_publish", {},
            auto_approve=False,
            live_execution=True,
            queue=queue,
        )
        assert proceed is False
        assert req_id  # non-empty
        assert queue.stats()["pending"] == 1


class TestHighCriticalAlwaysQueue:
    def test_high_enqueues(self, queue):
        proceed, req_id, level = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        assert proceed is False
        assert level is RiskLevel.HIGH
        assert req_id
        row = queue.get(req_id)
        assert row.action_type == "ad_campaign_create"
        assert row.risk_level is RiskLevel.HIGH

    def test_critical_enqueues(self, queue):
        proceed, req_id, level = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 200},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        assert proceed is False
        assert level is RiskLevel.CRITICAL
        assert queue.stats()["pending"] == 1

    def test_payload_persists_in_queue(self, queue):
        _, req_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20, "store": "deguar"},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        row = queue.get(req_id)
        assert row.payload == {
            "daily_budget_usd": 20, "store": "deguar",
        }


class TestApprovedRequestIdShortCircuit:
    def test_approved_request_id_lets_caller_proceed(self, queue):
        """Owner approved the action on a previous attempt.
        Caller retries with the request_id + the gate should
        see it's approved and let through without re-queueing."""
        # First pass: enqueue
        _, req_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        # Owner approves
        queue.approve(req_id, owner_id="dega")

        # Second pass: caller supplies approved_request_id
        proceed, returned_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            approved_request_id=req_id,
            queue=queue,
        )
        assert proceed is True
        assert returned_id == req_id
        # No new queue row
        assert queue.stats()["total"] == 1

    def test_pending_request_id_does_not_let_through(self, queue):
        """Supplied request_id that's still pending does NOT
        bypass the gate."""
        _, req_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        # Don't approve yet. Retry with the pending ID.
        proceed, new_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            approved_request_id=req_id,
            queue=queue,
        )
        assert proceed is False
        # Second attempt makes a new queue row (the old one
        # is still pending — we don't want to mutate it)
        assert new_id != req_id
        assert queue.stats()["pending"] == 2

    def test_denied_request_id_does_not_let_through(self, queue):
        _, req_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        queue.deny(req_id, reason="too aggressive")
        proceed, new_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            approved_request_id=req_id,
            queue=queue,
        )
        # Denied → treat as not-approved; new enqueue
        assert proceed is False
        assert new_id != req_id

    def test_approved_but_different_action_type_rejects(self, queue):
        """Defensive: an approval for ad_campaign_create should
        NOT let through a product_delete. Prevents ID reuse
        across different action types."""
        _, req_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            queue=queue,
        )
        queue.approve(req_id)
        proceed, new_id, _ = risk_gate.check_and_enqueue(
            "product_delete",  # different action!
            {"product_id": "123"},
            auto_approve=True,
            live_execution=True,
            approved_request_id=req_id,
            queue=queue,
        )
        assert proceed is False
        assert new_id != req_id

    def test_nonexistent_request_id_does_not_proceed(self, queue):
        proceed, new_id, _ = risk_gate.check_and_enqueue(
            "ad_campaign_create",
            {"daily_budget_usd": 20},
            auto_approve=True,
            live_execution=True,
            approved_request_id="does-not-exist",
            queue=queue,
        )
        assert proceed is False
        assert new_id  # fresh enqueue
