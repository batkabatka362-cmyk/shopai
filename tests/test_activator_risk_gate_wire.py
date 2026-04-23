"""Phase 2c-2 — risk gate wired into campaign_activator._step_execute.

Symmetric with tests/test_publisher_risk_gate_wire.py but for
the PAUSED→ACTIVE resume commit. Covers:

  * risk_gate_enabled=False (default): existing behaviour,
    no queue rows.
  * risk_gate_enabled=True + unapproved: 'pending' StepLog +
    one new queue row per resume attempt.
  * risk_gate_enabled=True + approved_request_id valid: gate
    short-circuits, resume proceeds to MetaAdsAdapter.
  * dry-run: gate never fires (no money commit).
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.contracts import RiskLevel
from core.system.approval_queue import (
    ApprovalQueue, reset_singleton_for_tests,
)
from execution.launch.campaign_activator import (
    ActivateRequest, CampaignActivator, StepLog,
)


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    """Tmp queue + live-execution env flag so dry_run doesn't
    short-circuit the gate in these tests."""
    reset_singleton_for_tests()
    from core.system import approval_queue as aq
    monkeypatch.setattr(
        aq, "_DEFAULT_DB_PATH", str(tmp_path / "q.db"),
    )
    monkeypatch.setenv("SHOPAI_ENABLE_LIVE_EXECUTION", "1")
    from core.system import approval_notifier as an
    an.reset_singleton_for_tests()
    yield aq.get_queue()
    reset_singleton_for_tests()
    an.reset_singleton_for_tests()


def _request(
    *,
    live: bool = True,
    risk_gate_enabled: bool = False,
    approved_request_id: str = "",
    auto_approve: bool = False,
) -> ActivateRequest:
    return ActivateRequest(
        campaign_id="fb_campaign_123",
        decision_id="dec-abc",
        daily_budget_usd=20.0,
        live=live,
        auto_approve=auto_approve,
        risk_gate_enabled=risk_gate_enabled,
        approved_request_id=approved_request_id,
    )


def _activator_with_fake_ads():
    """Activator with only the _step_execute surface exercised;
    other gates (readiness, constraints, moby) short-circuit to
    ok so we isolate the commit point."""
    act = CampaignActivator()

    class FakeResult:
        ok = True
        data = {"campaign_id": "fb_campaign_123"}

    class FakeAds:
        def execute(self, _cap, _params):
            return FakeResult()

    act._ads = FakeAds()
    return act


# ── Default: gate off ────────────────────────────────────


class TestGateDefaultOff:
    def test_no_queue_pressure(self, isolated_queue):
        """risk_gate_enabled=False → existing behaviour: no
        enqueue, resume goes straight to Meta Ads adapter."""
        act = _activator_with_fake_ads()
        # Default: execute the gate chain, but we just care that
        # the queue stays empty regardless of how early/late
        # the chain exits.
        req = _request()
        # _step_execute is called directly so tests skip the
        # upstream readiness/constraints gates entirely
        steps: list[StepLog] = []
        act._step_execute(req, steps, dry_run=False)
        assert isolated_queue.stats()["total"] == 0


# ── Gate enabled, unapproved → enqueues ─────────────────


class TestGateEnabledUnapproved:
    def test_enqueues_and_returns_pending(self, isolated_queue):
        act = _activator_with_fake_ads()
        req = _request(risk_gate_enabled=True)
        steps: list[StepLog] = []
        log = act._step_execute(req, steps, dry_run=False)
        assert log.status == "pending"
        assert isolated_queue.stats()["pending"] == 1
        # StepLog carries the request_id
        assert log.data["request_id"]
        assert log.data["risk_level"] in ("high", "critical")

    def test_message_surfaces_approve_hint(self, isolated_queue):
        act = _activator_with_fake_ads()
        req = _request(risk_gate_enabled=True)
        steps: list[StepLog] = []
        log = act._step_execute(req, steps, dry_run=False)
        assert "approve-request" in log.note
        req_id = log.data["request_id"]
        assert req_id in log.note

    def test_queue_row_includes_campaign_id(self, isolated_queue):
        """Payload persistence — approval message shows which
        campaign owner is approving."""
        act = _activator_with_fake_ads()
        req = _request(risk_gate_enabled=True)
        steps: list[StepLog] = []
        act._step_execute(req, steps, dry_run=False)
        row = isolated_queue.pending()[0]
        assert row.payload["campaign_id"] == "fb_campaign_123"
        assert row.payload["daily_budget_usd"] == 20.0


# ── Gate enabled + approved → proceeds ──────────────────


class TestGateEnabledApproved:
    def test_approved_resumes_campaign(self, isolated_queue):
        # First attempt — queue row created
        act = _activator_with_fake_ads()
        steps1: list[StepLog] = []
        log1 = act._step_execute(
            _request(risk_gate_enabled=True),
            steps1, dry_run=False,
        )
        req_id = log1.data["request_id"]
        # Owner approves out-of-band
        isolated_queue.approve(req_id, owner_id="dega")

        # Second attempt with approved_request_id
        act2 = _activator_with_fake_ads()
        steps2: list[StepLog] = []
        log2 = act2._step_execute(
            _request(
                risk_gate_enabled=True,
                approved_request_id=req_id,
            ),
            steps2, dry_run=False,
        )
        assert log2.status == "ok"
        # No new queue row created
        assert isolated_queue.stats()["total"] == 1


# ── Dry-run bypasses gate ────────────────────────────────


class TestDryRunBypass:
    def test_dry_run_no_enqueue(self, isolated_queue):
        """Dry-run means no money commit, so no queue pressure
        even when risk_gate_enabled=True."""
        act = _activator_with_fake_ads()
        req = _request(risk_gate_enabled=True)
        steps: list[StepLog] = []
        log = act._step_execute(req, steps, dry_run=True)
        assert log.status == "dry_run"
        assert isolated_queue.stats()["total"] == 0
