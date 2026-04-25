"""Phase 2c of the 4×4 matrix — risk gate wired into
publisher_bundle._step_launch_campaign.

Verifies:
  * risk_gate_enabled=False (default): existing behaviour —
    gate never fires, live launches proceed identically.
  * risk_gate_enabled=True + unapproved: launch returns
    pending_approval status + the queue has a new row.
  * risk_gate_enabled=True + approved_request_id valid:
    launch proceeds past the gate to the Meta Ads adapter.
  * Dry-run path: gate never fires regardless of
    risk_gate_enabled (no money commit in dry-run).
"""
from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

from core.contracts import RiskLevel
from core.system.approval_queue import (
    ApprovalQueue, reset_singleton_for_tests,
)
from execution.launch.publisher_bundle import (
    LaunchRequest, PublisherBundle,
)


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    """Point the risk_gate at a tmp queue + enable live
    execution so the dry_run short-circuit doesn't swallow
    the gate.  The gate tests are about the live-path
    behaviour specifically."""
    reset_singleton_for_tests()
    from core.system import approval_queue as aq
    monkeypatch.setattr(
        aq, "_DEFAULT_DB_PATH", str(tmp_path / "q.db"),
    )
    # Enable live execution so publisher_bundle's
    #   dry_run = not (request.live and _enable_live_execution())
    # resolves to dry_run=False when the test sets live=True.
    monkeypatch.setenv("SHOPAI_ENABLE_LIVE_EXECUTION", "1")
    # Also reset the notifier singleton
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
) -> LaunchRequest:
    return LaunchRequest(
        winner={
            "title": "Galaxy Projector",
            "price": 29.99,
            "image_url": "https://cdn.example/a.jpg",
            "url": "https://example.com/p",
            "margin_pct": 0.65,
        },
        shop_url="deguar.myshopify.com",
        api_key="shpat_fake",
        ad_budget_daily=20.0,
        live=live,
        risk_gate_enabled=risk_gate_enabled,
        approved_request_id=approved_request_id,
        decision_id="test-decision-123",
    )


def _bundle_with_fake_ads():
    """PublisherBundle with a mocked Meta Ads adapter so no
    real API calls happen."""
    bundle = PublisherBundle()

    # Stub every step except launch_campaign so tests focus
    # on the gate behaviour
    class FakeResult:
        ok = True
        data = {"campaign_id": "fb_campaign_99"}

    class FakeAds:
        def execute(self, _cap, _params):
            return FakeResult()

    bundle._ads = FakeAds()
    return bundle


# ── Default: gate off ────────────────────────────────────


class TestGateDefaultOff:
    def test_existing_behaviour_preserved(self, isolated_queue):
        """Default risk_gate_enabled=False → no enqueue, live
        path goes straight to the Meta Ads adapter."""
        bundle = _bundle_with_fake_ads()
        # Stub the other steps that would touch Shopify
        with patch.object(
            bundle, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            result = bundle.launch(_request(live=True))
        # Gate did not fire — no queue row
        assert isolated_queue.stats()["total"] == 0
        # Launch completed (campaign succeeded or one of the
        # stubbed steps may carry the final verdict; either way
        # NO pending_approval status from this path)
        assert all(
            s.status != "pending_approval" for s in result.steps
        )


# ── Gate enabled, first attempt → queues ────────────────


class TestGateEnabledUnapproved:
    def test_enqueues_and_returns_pending(self, isolated_queue):
        bundle = _bundle_with_fake_ads()
        with patch.object(
            bundle, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            result = bundle.launch(_request(
                live=True, risk_gate_enabled=True,
            ))
        # Queue has exactly 1 pending row
        assert isolated_queue.stats()["pending"] == 1
        # Find the launch_campaign step + check status
        campaign_steps = [
            s for s in result.steps
            if s.name == "launch_campaign"
        ]
        assert len(campaign_steps) == 1
        cs = campaign_steps[0]
        assert cs.status == "pending_approval"
        assert cs.data["risk_level"] in ("high", "critical")
        assert cs.data["request_id"]

    def test_request_id_surfaces_in_log(self, isolated_queue):
        """Owner-facing message should include the request_id
        so they can approve via Telegram."""
        bundle = _bundle_with_fake_ads()
        with patch.object(
            bundle, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            result = bundle.launch(_request(
                live=True, risk_gate_enabled=True,
            ))
        campaign = next(
            s for s in result.steps
            if s.name == "launch_campaign"
        )
        req_id = campaign.data["request_id"]
        # Message surfaces the id
        assert req_id in campaign.data["message"]
        assert "approve-request" in campaign.data["message"]


# ── Gate enabled + approved_request_id → proceeds ────────


class TestGateEnabledApproved:
    def test_approved_launches_campaign(self, isolated_queue):
        """First attempt queues. Owner approves out-of-band.
        Second attempt with approved_request_id set proceeds
        to the Meta Ads adapter."""
        # First attempt — queue row created
        bundle = _bundle_with_fake_ads()
        with patch.object(
            bundle, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            first = bundle.launch(_request(
                live=True, risk_gate_enabled=True,
            ))
        cs = next(
            s for s in first.steps
            if s.name == "launch_campaign"
        )
        req_id = cs.data["request_id"]
        # Owner approves
        isolated_queue.approve(req_id, owner_id="dega")

        # Second attempt with approved_request_id
        bundle2 = _bundle_with_fake_ads()
        with patch.object(
            bundle2, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle2, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle2, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle2, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            second = bundle2.launch(_request(
                live=True, risk_gate_enabled=True,
                approved_request_id=req_id,
            ))
        cs2 = next(
            s for s in second.steps
            if s.name == "launch_campaign"
        )
        # No new queue row created
        assert isolated_queue.stats()["total"] == 1
        # Campaign launched
        assert cs2.status == "success"
        assert cs2.data.get("campaign_id") == "fb_campaign_99"


# ── Dry-run bypasses the gate ────────────────────────────


class TestDryRunBypassesGate:
    def test_dry_run_gate_enabled_no_enqueue(
        self, isolated_queue,
    ):
        """Dry-run = no money committed, so no queue pressure
        even when risk_gate_enabled=True."""
        bundle = _bundle_with_fake_ads()
        with patch.object(
            bundle, "_step_generate_copy",
            return_value=_ok_step(
                "copy", {"title": "x", "description": "x"},
            ),
        ), patch.object(
            bundle, "_step_create_product",
            return_value=_ok_step(
                "create_product",
                {"product_id": 1, "handle": "x"},
            ),
        ), patch.object(
            bundle, "_step_generate_videos",
            return_value=_ok_step("videos", {}),
        ), patch.object(
            bundle, "_step_eu_ai_compliance",
            return_value=_ok_step("compliance", {}),
        ):
            result = bundle.launch(_request(
                live=False,   # dry-run
                risk_gate_enabled=True,
            ))
        # Gate short-circuited via dry-run path; no queue row
        assert isolated_queue.stats()["total"] == 0
        cs = next(
            s for s in result.steps
            if s.name == "launch_campaign"
        )
        assert cs.status == "dry_run"


# ── Helpers ──────────────────────────────────────────────


def _ok_step(name: str, data: dict) -> "StepLog":
    from execution.launch.publisher_bundle import StepLog
    import time
    return StepLog(
        name=name, status="success", data=data, ts=time.time(),
    )
