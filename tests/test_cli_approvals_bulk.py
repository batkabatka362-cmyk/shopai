"""Tests for ``shopai approvals approve-all`` — bulk-approve PENDING
actions matching engine + confidence filters.

The single-action approve verb (covered in test_cli_approvals.py) is
fine when there's one thing to review. Operators reviewing a triage
batch — "20 cart_recovery proposals at 0.9 confidence, approve and
run them all" — need a single command that filters + approves +
optionally executes.
"""
from __future__ import annotations

import argparse
import importlib.util
from io import StringIO
from pathlib import Path
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


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


def _enqueue(queue, *, engine: str, confidence: float | None = None):
    return queue.enqueue(
        engine=engine, action_type="probe",
        capability="SHOPIFY_CREATE_DISCOUNT", params={},
        narrative="", confidence=confidence,
    )


# ─── happy paths ──────────────────────────────────────────────────


class TestApproveAll:

    def test_empty_queue_clean_exit(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=None, by="op",
                reason="bulk_approve", execute=False, dry_run=False),
        )
        assert code == 0
        assert "No PENDING actions matched" in out

    def test_no_matches_with_filter_shows_filter(
        self, cli, isolated_queue,
    ):
        _enqueue(isolated_queue, engine="cart_recovery", confidence=0.7)
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine="loyalty", min_confidence=None, by="op",
                reason="", execute=False, dry_run=False),
        )
        assert code == 0
        assert "No PENDING actions matched" in out
        assert "engine=loyalty" in out

    def test_no_filter_approves_all(self, cli, isolated_queue):
        a = _enqueue(isolated_queue, engine="cart_recovery", confidence=0.85)
        b = _enqueue(isolated_queue, engine="loyalty", confidence=0.9)
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=None, by="op",
                reason="bulk", execute=False, dry_run=False),
        )
        assert code == 0
        assert "Approved 2 action(s)" in out

        from core.approval.queue import ApprovalStatus
        for action in (a, b):
            assert isolated_queue.get(action.id).status == (
                ApprovalStatus.APPROVED
            )

    def test_engine_filter_skips_others(self, cli, isolated_queue):
        cart = _enqueue(
            isolated_queue, engine="cart_recovery", confidence=0.9,
        )
        loyalty = _enqueue(
            isolated_queue, engine="loyalty", confidence=0.9,
        )
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine="cart_recovery", min_confidence=None,
                by="op", reason="", execute=False, dry_run=False),
        )
        assert code == 0
        assert "Approved 1 action(s)" in out

        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(cart.id).status == (
            ApprovalStatus.APPROVED
        )
        # Other engine untouched
        assert isolated_queue.get(loyalty.id).status == (
            ApprovalStatus.PENDING
        )

    def test_min_confidence_floor(self, cli, isolated_queue):
        low = _enqueue(isolated_queue, engine="x", confidence=0.7)
        mid = _enqueue(isolated_queue, engine="x", confidence=0.85)
        high = _enqueue(isolated_queue, engine="x", confidence=0.95)
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=0.9, by="op",
                reason="", execute=False, dry_run=False),
        )
        assert code == 0
        assert "Approved 1 action(s)" in out
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(low.id).status == ApprovalStatus.PENDING
        assert isolated_queue.get(mid.id).status == ApprovalStatus.PENDING
        assert isolated_queue.get(high.id).status == (
            ApprovalStatus.APPROVED
        )

    def test_missing_confidence_treated_as_zero(
        self, cli, isolated_queue,
    ):
        """Actions without a confidence number must NOT slip past a
        min-confidence floor — they should be treated as 0.0."""
        _enqueue(isolated_queue, engine="x", confidence=None)
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=0.5, by="op",
                reason="", execute=False, dry_run=False),
        )
        assert code == 0
        assert "No PENDING actions matched" in out

    def test_combined_engine_plus_confidence(
        self, cli, isolated_queue,
    ):
        match = _enqueue(
            isolated_queue, engine="cart_recovery", confidence=0.95,
        )
        # Wrong engine, high confidence
        _enqueue(isolated_queue, engine="loyalty", confidence=0.95)
        # Right engine, low confidence
        _enqueue(isolated_queue, engine="cart_recovery", confidence=0.7)

        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine="cart_recovery", min_confidence=0.9,
                by="op", reason="", execute=False, dry_run=False),
        )
        assert code == 0
        assert "Approved 1 action(s)" in out
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(match.id).status == (
            ApprovalStatus.APPROVED
        )


# ─── dry run ──────────────────────────────────────────────────────


class TestDryRun:

    def test_dry_run_lists_without_writing(self, cli, isolated_queue):
        a = _enqueue(isolated_queue, engine="cart_recovery", confidence=0.9)
        out, code = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=None, by="op",
                reason="", execute=False, dry_run=True),
        )
        assert code == 0
        assert "Dry run:" in out
        assert "1 action(s) would be approved" in out
        assert a.id in out
        # No state change
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.PENDING

    def test_dry_run_shows_confidence(self, cli, isolated_queue):
        _enqueue(isolated_queue, engine="x", confidence=0.87)
        out, _ = _capture(
            cli._cmd_approvals_approve_all,
            _ns(engine=None, min_confidence=None, by="op",
                reason="", execute=False, dry_run=True),
        )
        assert "conf=0.87" in out


# ─── execute ──────────────────────────────────────────────────────


class TestExecuteFlag:

    def test_execute_flag_runs_dispatcher(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="catalog", action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["t"]},
            narrative="", confidence=0.95,
        )
        with patch(
            "core.approval.dispatchers._router_call",
            return_value=(True, {"applied": True}),
        ):
            out, code = _capture(
                cli._cmd_approvals_approve_all,
                _ns(engine=None, min_confidence=None, by="op",
                    reason="", execute=True, dry_run=False),
            )
        assert code == 0
        assert "Approved 1 action(s), executed 1" in out
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == (
            ApprovalStatus.EXECUTED
        )
