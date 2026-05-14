"""Tests for ``shopai approvals recent <status>`` — operator
triage feed.

The existing ``pending`` verb covered PENDING and ``status`` showed
the last few EXECUTED, but operators triaging review issues need
to see ``FAILED`` / ``REJECTED`` / ``EXPIRED`` actions with their
reason strings. ``recent <status>`` generalises the pattern.
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


# ─── ApprovalQueue.list_by_status ─────────────────────────────────


class TestListByStatus:

    def test_empty_for_unused_status(self, isolated_queue):
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.list_by_status(
            ApprovalStatus.FAILED,
        ) == []

    def test_pending_sorted_oldest_first(self, isolated_queue):
        from core.approval.queue import ApprovalStatus
        first = isolated_queue.enqueue(
            engine="x", action_type="a", capability="X",
            params={}, narrative="",
        )
        second = isolated_queue.enqueue(
            engine="x", action_type="b", capability="X",
            params={}, narrative="",
        )
        result = isolated_queue.list_by_status(ApprovalStatus.PENDING)
        # Oldest first — first comes before second (FIFO review queue)
        assert [a.id for a in result] == [first.id, second.id]

    def test_executed_sorted_newest_first(self, isolated_queue):
        from core.approval.queue import ApprovalStatus
        a1 = isolated_queue.enqueue(
            engine="x", action_type="a", capability="X",
            params={}, narrative="",
        )
        isolated_queue.approve(a1.id)
        isolated_queue._transition(
            a1.id,
            from_status=ApprovalStatus.APPROVED,
            to_status=ApprovalStatus.EXECUTED,
            decided_by="t", reason="",
        )
        a2 = isolated_queue.enqueue(
            engine="x", action_type="b", capability="X",
            params={}, narrative="",
        )
        isolated_queue.approve(a2.id)
        isolated_queue._transition(
            a2.id,
            from_status=ApprovalStatus.APPROVED,
            to_status=ApprovalStatus.EXECUTED,
            decided_by="t", reason="",
        )
        # Most recently decided first
        result = isolated_queue.list_by_status(ApprovalStatus.EXECUTED)
        assert result[0].id == a2.id

    def test_engine_filter(self, isolated_queue):
        from core.approval.queue import ApprovalStatus
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="x",
            capability="X", params={}, narrative="",
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="x",
            capability="X", params={}, narrative="",
        )
        result = isolated_queue.list_by_status(
            ApprovalStatus.PENDING, engine="cart_recovery",
        )
        assert [r.id for r in result] == [a.id]

    def test_limit(self, isolated_queue):
        from core.approval.queue import ApprovalStatus
        for _ in range(5):
            isolated_queue.enqueue(
                engine="x", action_type="y", capability="X",
                params={}, narrative="",
            )
        result = isolated_queue.list_by_status(
            ApprovalStatus.PENDING, limit=3,
        )
        assert len(result) == 3


# ─── shopai approvals recent <status> ────────────────────────────


class TestRecentCLI:

    def test_empty_status_message(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_recent,
            _ns(status="failed", engine=None, limit=10),
        )
        assert code == 0
        assert "No FAILED actions" in out

    def test_empty_with_engine_filter(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_recent,
            _ns(status="failed", engine="loyalty", limit=10),
        )
        assert code == 0
        assert "No FAILED actions for engine 'loyalty'" in out

    def test_lists_pending(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="mint_code",
            capability="X", params={}, narrative="",
        )
        out, code = _capture(
            cli._cmd_approvals_recent,
            _ns(status="pending", engine=None, limit=10),
        )
        assert code == 0
        assert "Recent PENDING actions (1)" in out
        assert a.id[:18] in out
        assert "cart_recovery/mint_code" in out

    def test_failed_surfaces_error(self, cli, isolated_queue):
        from core.approval.queue import ApprovalStatus
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="X",
            params={}, narrative="",
        )
        isolated_queue.approve(a.id)
        # Attach a failure result
        isolated_queue.attach_result(
            a.id, success=False, result={"error": "router_down"},
        )
        out, code = _capture(
            cli._cmd_approvals_recent,
            _ns(status="failed", engine=None, limit=10),
        )
        assert code == 0
        assert "Recent FAILED actions" in out
        assert "err=router_down" in out

    def test_rejected_surfaces_reason(self, cli, isolated_queue):
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="X",
            params={}, narrative="",
        )
        isolated_queue.reject(
            a.id, decided_by="op", reason="too risky",
        )
        out, code = _capture(
            cli._cmd_approvals_recent,
            _ns(status="rejected", engine=None, limit=10),
        )
        assert code == 0
        assert "reason=too risky" in out

    def test_expired_surfaces_ttl_reason(self, cli, isolated_queue):
        import time
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="X",
            params={}, narrative="",
        )
        # Backdate
        with isolated_queue._conn:
            isolated_queue._conn.execute(
                "UPDATE pending_actions SET proposed_at = ? WHERE id = ?",
                (time.time() - 3600, a.id),
            )
        isolated_queue.expire_stale(max_age_seconds=60)
        out, _ = _capture(
            cli._cmd_approvals_recent,
            _ns(status="expired", engine=None, limit=10),
        )
        assert "ttl_exceeded" in out

    def test_engine_filter_passes_through(self, cli, isolated_queue):
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="x", capability="X",
            params={}, narrative="",
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="y", capability="X",
            params={}, narrative="",
        )
        out, _ = _capture(
            cli._cmd_approvals_recent,
            _ns(status="pending", engine="cart_recovery", limit=10),
        )
        assert "cart_recovery/" in out
        assert "loyalty/" not in out
