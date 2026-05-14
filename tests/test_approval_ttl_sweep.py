"""Tests for the approval-queue TTL sweep — ``expire_stale`` on the
queue + ``shopai approvals sweep`` CLI verb.

The lifecycle docstring in ``core/approval/queue.py`` originally flagged
``ApprovalStatus.EXPIRED`` as "TTL only, not auto-applied in v1". This
file covers the v2 sweep that closes that gap: a long-pending action
that no operator has reviewed in N days gets bulk-transitioned to
EXPIRED, with an ``approval.expired`` hook fanning out so the brain
stack can learn from review starvation.
"""
from __future__ import annotations

import importlib.util
import time
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


def _enqueue_with_age(queue, *, age_seconds: float, engine: str = "test"):
    """Backdate a newly-queued action's ``proposed_at`` so the sweep
    treats it as ``age_seconds`` old."""
    action = queue.enqueue(
        engine=engine, action_type="probe",
        capability="X", params={}, narrative="",
    )
    backdated = time.time() - age_seconds
    with queue._conn:
        queue._conn.execute(
            "UPDATE pending_actions SET proposed_at = ? WHERE id = ?",
            (backdated, action.id),
        )
    return action


# ─── ApprovalQueue.expire_stale ──────────────────────────────────


class TestExpireStale:

    def test_empty_queue_returns_empty(self, isolated_queue):
        assert isolated_queue.expire_stale(max_age_seconds=60) == []

    def test_no_stale_actions_returns_empty(self, isolated_queue):
        isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        # Just queued — not old enough
        assert isolated_queue.expire_stale(max_age_seconds=60) == []

    def test_old_action_transitions_to_expired(self, isolated_queue):
        a = _enqueue_with_age(isolated_queue, age_seconds=3600)
        expired = isolated_queue.expire_stale(max_age_seconds=60)
        assert len(expired) == 1
        assert expired[0].id == a.id
        from core.approval.queue import ApprovalStatus
        assert expired[0].status == ApprovalStatus.EXPIRED
        # decided_at set, decision_reason mentions TTL
        assert expired[0].decided_at is not None
        assert "ttl_exceeded" in (expired[0].decision_reason or "")

    def test_only_old_actions_transition(self, isolated_queue):
        old = _enqueue_with_age(isolated_queue, age_seconds=3600)
        young = isolated_queue.enqueue(
            engine="y", action_type="probe", capability="X",
            params={}, narrative="",
        )
        expired = isolated_queue.expire_stale(max_age_seconds=60)
        assert [a.id for a in expired] == [old.id]
        # Young action still PENDING
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(young.id).status == (
            ApprovalStatus.PENDING
        )

    def test_only_pending_actions_targeted(self, isolated_queue):
        """Already-resolved actions are immune to TTL sweep."""
        approved_old = _enqueue_with_age(isolated_queue, age_seconds=3600)
        isolated_queue.approve(approved_old.id)
        # Now ancient AND approved — should be skipped
        rejected_old = _enqueue_with_age(isolated_queue, age_seconds=3600)
        isolated_queue.reject(rejected_old.id)

        expired = isolated_queue.expire_stale(max_age_seconds=60)
        assert expired == []

    def test_emits_approval_expired_hook(self, isolated_queue):
        a = _enqueue_with_age(isolated_queue, age_seconds=3600)
        with patch("core.approval.queue._emit_hook") as emit:
            isolated_queue.expire_stale(max_age_seconds=60)
        # Find the approval.expired call
        expired_calls = [
            c for c in emit.call_args_list
            if c.args and c.args[0] == "approval.expired"
        ]
        assert len(expired_calls) == 1
        payload = expired_calls[0].args[1]
        assert payload["action_id"] == a.id
        assert "age_seconds" in payload

    def test_bulk_expire_multiple(self, isolated_queue):
        ids = [
            _enqueue_with_age(isolated_queue, age_seconds=3600).id
            for _ in range(5)
        ]
        expired = isolated_queue.expire_stale(max_age_seconds=60)
        assert sorted(a.id for a in expired) == sorted(ids)
        # And stats reflects the transition
        stats = isolated_queue.stats()
        assert stats["pending"] == 0
        assert stats["expired"] == 5


# ─── _parse_age_spec ──────────────────────────────────────────────


class TestParseAgeSpec:

    def test_seconds(self, cli):
        assert cli._parse_age_spec("60s") == 60.0
        assert cli._parse_age_spec("0s") == 0.0

    def test_minutes(self, cli):
        assert cli._parse_age_spec("30m") == 1800.0

    def test_hours(self, cli):
        assert cli._parse_age_spec("24h") == 86400.0

    def test_days(self, cli):
        assert cli._parse_age_spec("7d") == 7 * 86400.0

    def test_bare_int_is_seconds(self, cli):
        assert cli._parse_age_spec("3600") == 3600.0

    def test_invalid_returns_none(self, cli):
        assert cli._parse_age_spec("garbage") is None
        assert cli._parse_age_spec("") is None
        assert cli._parse_age_spec("7x") is None


# ─── shopai approvals sweep ───────────────────────────────────────


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
    import argparse
    return argparse.Namespace(**kwargs)


class TestSweepCLI:

    def test_invalid_age_spec_exits_1(self, cli, isolated_queue):
        out, code = _capture(
            cli._cmd_approvals_sweep,
            _ns(older_than="garbage", dry_run=False),
        )
        assert code == 1
        assert "Invalid --older-than" in out

    def test_no_stale_actions_clean_exit(self, cli, isolated_queue):
        # Queue has only fresh actions
        isolated_queue.enqueue(
            engine="x", action_type="y", capability="z",
            params={}, narrative="",
        )
        out, code = _capture(
            cli._cmd_approvals_sweep,
            _ns(older_than="7d", dry_run=False),
        )
        assert code == 0
        assert "no pending actions" in out.lower()

    def test_dry_run_lists_without_writing(self, cli, isolated_queue):
        a = _enqueue_with_age(isolated_queue, age_seconds=3600)
        out, code = _capture(
            cli._cmd_approvals_sweep,
            _ns(older_than="1m", dry_run=True),
        )
        assert code == 0
        assert "Dry run:" in out
        assert a.id in out
        # And no actual transition happened
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.PENDING

    def test_live_sweep_expires_and_reports(self, cli, isolated_queue):
        a = _enqueue_with_age(isolated_queue, age_seconds=3600)
        out, code = _capture(
            cli._cmd_approvals_sweep,
            _ns(older_than="1m", dry_run=False),
        )
        assert code == 0
        assert "1 action(s) expired" in out
        assert a.id in out
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.EXPIRED
