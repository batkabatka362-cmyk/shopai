"""Tests for ``shopai approvals doctor`` — aggregate approval-
queue health check.

Verifies:
  - All 5 sections render in pass / fail / warn / info states
  - --json emits structured envelope with all sections
  - Fatal sections (Pattern K, stale pending) fail the doctor
  - Warning sections (high failure rate) don't fail it
  - Configurable thresholds (--stale-pending-hours,
    --failure-rate-warn) actually flow through
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
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
        stale_pending_hours=24.0,
        failure_rate_warn=0.25,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── Happy path ────────────────────────────────────────────────


class TestHappyPath:

    def test_doctor_runs_clean(self, cli):
        """The live registry passes the doctor today."""
        out, code = _capture(
            cli._cmd_approvals_doctor, _ns(),
        )
        assert code == 0
        assert "Overall: OK" in out
        # All five sections render
        assert "Pattern K dispatchers" in out
        assert "Pending queue" in out
        assert "Recent dispatch" in out
        assert "Quarantine" in out
        assert "Auto-approve" in out


# ─── JSON envelope ─────────────────────────────────────────────


class TestJson:

    def test_json_envelope_shape(self, cli):
        out, code = _capture(
            cli._cmd_approvals_doctor, _ns(json=True),
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert set(data["sections"].keys()) == {
            "pattern_k_dispatchers",
            "pending_queue",
            "recent_dispatch",
            "quarantine",
            "auto_approve",
        }

    def test_json_pending_queue_section(self, cli):
        out, _ = _capture(
            cli._cmd_approvals_doctor, _ns(json=True),
        )
        section = json.loads(out)["sections"]["pending_queue"]
        # pending_count is always present; threshold echoed
        assert "pending_count" in section
        assert section["stale_threshold_hours"] == 24.0


# ─── Fatal failure sections ────────────────────────────────────


class TestFatalSections:

    def test_pattern_k_gap_fails_doctor(self, cli):
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
                cli._cmd_approvals_doctor, _ns(),
            )
        assert code == 1
        assert "FAILED" in out
        assert "[FAIL] Pattern K" in out
        # Remediation hint surfaces
        assert "core/approval/dispatchers.py" in out

    def test_stale_pending_fails_doctor(self, cli):
        """Patch list_pending to return a fake old action."""
        from core.approval.queue import (
            ApprovalAction,
            ApprovalStatus,
        )
        old = ApprovalAction(
            id="old-1",
            engine="x",
            action_type="apply_thing",
            capability="SHOPIFY_LIST_ORDERS",
            params={},
            narrative="stale",
            confidence=0.8,
            status=ApprovalStatus.PENDING,
            # 48h ago — beyond default 24h threshold
            proposed_at=time.time() - 48 * 3600,
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
        )

        from core.approval import get_approval_queue
        live_queue = get_approval_queue()

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
                cli._cmd_approvals_doctor, _ns(),
            )
        assert code == 1
        assert "[FAIL] Pending queue" in out
        # Threshold + hint both surface
        assert "24" in out
        assert "fix:" in out

    def test_short_threshold_flips_to_fail(self, cli):
        """Set threshold to 0.01h so a 1-minute-old PENDING fails."""
        from core.approval.queue import (
            ApprovalAction,
            ApprovalStatus,
        )
        recent = ApprovalAction(
            id="r-1",
            engine="x",
            action_type="t",
            capability="SHOPIFY_LIST_ORDERS",
            params={},
            narrative="",
            confidence=0.8,
            status=ApprovalStatus.PENDING,
            proposed_at=time.time() - 120,  # 2 min old
            decided_at=None,
            decided_by=None,
            decision_reason=None,
            result=None,
        )

        from core.approval import get_approval_queue
        live_queue = get_approval_queue()

        class FakeQueue:
            def list_pending(self, *, limit=1000):
                return [recent]

            def stats(self):
                return live_queue.stats()

        with patch(
            "core.approval.get_approval_queue",
            return_value=FakeQueue(),
        ):
            out, code = _capture(
                cli._cmd_approvals_doctor,
                _ns(stale_pending_hours=0.01),
            )
        assert code == 1
        assert "[FAIL] Pending queue" in out


# ─── Warning sections (don't fail doctor) ─────────────────────


class TestWarnSections:

    def test_high_failure_rate_warns_but_doesnt_fail(self, cli):
        from core.approval import get_approval_queue
        live_queue = get_approval_queue()

        class FakeQueue:
            def list_pending(self, *, limit=1000):
                return []

            def stats(self):
                return {
                    "executed": 4,
                    "failed": 6,
                    "pending": 0,
                    "approved": 0,
                    "rejected": 0,
                    "expired": 0,
                }

        with patch(
            "core.approval.get_approval_queue",
            return_value=FakeQueue(),
        ):
            out, code = _capture(
                cli._cmd_approvals_doctor, _ns(),
            )
        # 60% failure rate >= 25% threshold → warn but pass
        assert code == 0
        assert "[WARN] Recent dispatch" in out
        assert "60.0%" in out
        assert "investigate" in out

    def test_low_decided_count_skips_warn(self, cli):
        """With <5 decisions the doctor shouldn't warn even at
        100% failure — sample size too small for signal."""
        from core.approval import get_approval_queue
        live_queue = get_approval_queue()

        class FakeQueue:
            def list_pending(self, *, limit=1000):
                return []

            def stats(self):
                # 2 failed, 0 executed — 100% rate, only 2 sample
                return {
                    "executed": 0,
                    "failed": 2,
                    "pending": 0,
                    "approved": 0,
                    "rejected": 0,
                    "expired": 0,
                }

        with patch(
            "core.approval.get_approval_queue",
            return_value=FakeQueue(),
        ):
            out, code = _capture(
                cli._cmd_approvals_doctor, _ns(),
            )
        assert code == 0
        assert "[pass] Recent dispatch" in out


# ─── Informational sections ───────────────────────────────────


class TestInfoSections:

    def test_empty_quarantine_renders_info(self, cli):
        """Default state — no exemptions, no releases. Info, not
        warn — empty quarantine state is healthy."""
        out, code = _capture(
            cli._cmd_approvals_doctor, _ns(),
        )
        assert code == 0
        assert "[info] Quarantine" in out

    def test_empty_auto_approve_renders_info(self, cli):
        out, code = _capture(
            cli._cmd_approvals_doctor, _ns(),
        )
        assert code == 0
        assert "[info] Auto-approve" in out


# ─── Resilience ───────────────────────────────────────────────


class TestResilience:

    def test_pattern_k_audit_failure_renders_unavailable(self, cli):
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            side_effect=RuntimeError("audit broken"),
        ):
            out, code = _capture(
                cli._cmd_approvals_doctor, _ns(),
            )
        assert "[??] Pattern K" in out
        # Unavailable is not a fatal failure — doctor stays OK
        assert code == 0

    def test_queue_failure_renders_unavailable(self, cli):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            out, _ = _capture(
                cli._cmd_approvals_doctor, _ns(),
            )
        assert "[??] Pending queue" in out
        assert "[??] Recent dispatch" in out
