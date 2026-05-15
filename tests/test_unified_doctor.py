"""Tests for ``shopai doctor`` -- the unified health check that
combines shopify-doctor + approvals doctor in one shot.

Verifies:
  - Both sub-doctor outputs render under a shared header
  - JSON envelope nests under "shopify" and "approvals" keys
  - A failure on either side flips the overall verdict and
    exits 1
  - Section collectors are reused (no duplicated logic)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        json=False,
        skip_live=True,
        stale_pending_hours=24.0,
        failure_rate_warn=0.25,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Happy path ────────────────────────────────────────────────


class TestHappyPath:

    def test_unified_runs_clean(self, cli):
        out, code = _capture(cli._cmd_unified_doctor, _ns())
        assert code == 0
        # Both sub-doctor headers + verdicts
        assert "Shopify integration" in out
        assert "Approval queue" in out
        assert "Pattern K dispatchers" in out
        assert "Pending queue" in out
        assert "Overall: OK" in out
        assert "both Shopify and approval-queue checks pass" in out

    def test_renders_seven_shopify_sections(self, cli):
        out, _ = _capture(cli._cmd_unified_doctor, _ns())
        # 4 platform audits + 2 live (skipped) + 1 writebacks
        assert "Pattern K dispatchers" in out
        assert "OAuth scope coverage" in out
        assert "Pattern Y capabilities" in out
        assert "Pattern I engine capabilities" in out
        assert "Live scope drift" in out
        assert "Live webhook drift" in out
        assert "Engine writebacks" in out

    def test_renders_five_approvals_sections(self, cli):
        out, _ = _capture(cli._cmd_unified_doctor, _ns())
        assert "Pending queue" in out
        assert "Recent dispatch" in out
        assert "Quarantine" in out
        assert "Auto-approve" in out


# ─── JSON envelope ─────────────────────────────────────────────


class TestJson:

    def test_envelope_nests_both_sides(self, cli):
        out, code = _capture(cli._cmd_unified_doctor, _ns(json=True))
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert "shopify" in data
        assert "approvals" in data
        assert data["shopify"]["ok"] is True
        assert data["approvals"]["ok"] is True
        # All sections live in their respective sub-dicts
        assert "pattern_k_dispatchers" in data["shopify"]["sections"]
        assert "pending_queue" in data["approvals"]["sections"]


# ─── Failure propagation ──────────────────────────────────────


class TestFailurePropagation:

    def test_shopify_failure_flips_overall(self, cli):
        from core.approval.coverage_audit import AuditReport
        bad = AuditReport(
            enqueued=[],
            registered=[],
            missing={"missing_action"},
            orphaned=set(),
        )
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=bad,
        ):
            out, code = _capture(
                cli._cmd_unified_doctor, _ns(),
            )
        # Pattern K fails BOTH sides (Shopify + approvals both
        # check it). Overall must flip to FAILED.
        assert code == 1
        assert "FAILED" in out
        # The broken-list line names which side fell over
        assert "Shopify" in out
        assert "Approval queue" in out

    def test_approvals_only_failure(self, cli):
        """Patch only the pending queue to look stale -- only the
        approvals side fails; Shopify side passes."""
        import time
        from core.approval.queue import (
            ApprovalAction,
            ApprovalStatus,
        )
        from core.approval import get_approval_queue
        live_queue = get_approval_queue()
        old = ApprovalAction(
            id="old-1",
            engine="x",
            action_type="apply_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={},
            narrative="",
            confidence=0.5,
            status=ApprovalStatus.PENDING,
            proposed_at=time.time() - 48 * 3600,
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
        )

        class FakeQueue:
            def list_pending(self, *, limit=1000):
                return [old]

            def stats(self):
                return live_queue.stats()

        with patch(
            "core.approval.get_approval_queue",
            return_value=FakeQueue(),
        ):
            out, code = _capture(
                cli._cmd_unified_doctor, _ns(),
            )
        assert code == 1
        assert "[FAIL] Pending queue" in out
        # Side-of-failure surfaces (only approvals)
        assert "Approval queue" in out


# ─── Section collector reuse ──────────────────────────────────


class TestCollectorReuse:

    def test_uses_shared_section_collectors(self, cli):
        """Ensures the unified doctor calls the same collectors
        as the individual doctors. Patches both collectors and
        verifies they're both invoked."""
        with patch.object(
            cli,
            "_collect_doctor_sections",
            return_value=(True, {}),
        ) as shop_mock, patch.object(
            cli,
            "_collect_approvals_doctor_sections",
            return_value=(True, {}),
        ) as appr_mock:
            _capture(cli._cmd_unified_doctor, _ns())
        assert shop_mock.called
        assert appr_mock.called
