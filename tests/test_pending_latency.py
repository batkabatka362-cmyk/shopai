"""Tests for ``pending_latency_stats`` + CLI surface.

Surfaces engines producing un-actionable proposals — either
spammy (too many) or low-quality (operators ignore them).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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
def isolated_state(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"queue": fresh}
    fresh._conn.close()


def _seed_pending(q, engine, count, *, age_seconds=0):
    """Seed N PENDING actions for engine, optionally backdated."""
    for _ in range(count):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        if age_seconds:
            q._conn.execute(
                "UPDATE pending_actions SET proposed_at = ? "
                "WHERE id = ?",
                (time.time() - age_seconds, a.id),
            )
    if age_seconds:
        q._conn.commit()


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
    defaults = dict(older_than=None, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── pending_latency_stats() ───────────────────────────────────


class TestPendingLatencyStats:

    def test_empty_state_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        assert q.pending_latency_stats() == {}

    def test_decided_actions_not_counted(self, isolated_state):
        """Engines with only APPROVED/EXECUTED actions don't
        appear — the stat is PENDING-only."""
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="decided", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        assert q.pending_latency_stats() == {}

    def test_single_pending_action(self, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "engine_a", count=1)
        stats = q.pending_latency_stats()
        assert "engine_a" in stats
        assert stats["engine_a"]["pending_count"] == 1
        # All three aggregates equal for n=1
        assert stats["engine_a"]["oldest_age_seconds"] >= 0
        assert (
            stats["engine_a"]["oldest_age_seconds"]
            == stats["engine_a"]["median_age_seconds"]
            == stats["engine_a"]["mean_age_seconds"]
        )

    def test_multiple_engines_separate(self, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "a", count=3)
        _seed_pending(q, "b", count=5)
        stats = q.pending_latency_stats()
        assert stats["a"]["pending_count"] == 3
        assert stats["b"]["pending_count"] == 5

    def test_oldest_age_captures_oldest(self, isolated_state):
        """Mixed-age pendings: oldest_age reflects the oldest
        one, not the mean."""
        q = isolated_state["queue"]
        # 2 fresh + 1 very old
        _seed_pending(q, "spammy", count=2)
        _seed_pending(q, "spammy", count=1, age_seconds=86400 * 5)
        stats = q.pending_latency_stats()
        # 5 days = 432000s; allow some clock slop
        assert stats["spammy"]["oldest_age_seconds"] >= 86400 * 4

    def test_median_with_odd_count(self, isolated_state):
        """3 ages → median is the middle one."""
        q = isolated_state["queue"]
        _seed_pending(q, "e", count=1, age_seconds=10)
        _seed_pending(q, "e", count=1, age_seconds=100)
        _seed_pending(q, "e", count=1, age_seconds=1000)
        stats = q.pending_latency_stats()
        # Middle of [10, 100, 1000] = 100
        # Allow ±2s slop for test execution time
        assert 95 <= stats["e"]["median_age_seconds"] <= 105

    def test_median_with_even_count(self, isolated_state):
        """4 ages → median is mean of the middle two."""
        q = isolated_state["queue"]
        _seed_pending(q, "e", count=1, age_seconds=10)
        _seed_pending(q, "e", count=1, age_seconds=100)
        _seed_pending(q, "e", count=1, age_seconds=200)
        _seed_pending(q, "e", count=1, age_seconds=1000)
        stats = q.pending_latency_stats()
        # Median of [10, 100, 200, 1000] = (100+200)/2 = 150
        assert 145 <= stats["e"]["median_age_seconds"] <= 155

    def test_mean_calculated_correctly(self, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "e", count=1, age_seconds=100)
        _seed_pending(q, "e", count=1, age_seconds=200)
        stats = q.pending_latency_stats()
        # Mean = 150
        assert 145 <= stats["e"]["mean_age_seconds"] <= 155


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_friendly_message(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_pending_latency, _ns(),
        )
        assert code == 0
        assert "No engines have PENDING actions" in out

    def test_lists_engines_with_pending(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "spammy", count=5)
        out, _ = _capture(
            cli._cmd_approvals_pending_latency, _ns(),
        )
        assert "Pending-action latency" in out
        assert "spammy" in out

    def test_oldest_engine_sorts_first(self, cli, isolated_state):
        """Most-stale engines surface at the top — triage UX."""
        q = isolated_state["queue"]
        _seed_pending(q, "fresh", count=1)
        _seed_pending(q, "stale", count=1, age_seconds=86400 * 5)
        out, _ = _capture(
            cli._cmd_approvals_pending_latency, _ns(),
        )
        stale_pos = out.find("stale")
        fresh_pos = out.find("fresh")
        assert 0 <= stale_pos < fresh_pos

    def test_older_than_filter(self, cli, isolated_state):
        """--older-than 24h hides engines whose oldest pending
        is fresher than the cutoff."""
        q = isolated_state["queue"]
        _seed_pending(q, "fresh", count=1)
        _seed_pending(q, "stale", count=1, age_seconds=86400 * 5)
        out, _ = _capture(
            cli._cmd_approvals_pending_latency,
            _ns(older_than="24h"),
        )
        assert "stale" in out
        assert "fresh" not in out

    def test_older_than_empty_friendly(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "fresh", count=1)
        out, _ = _capture(
            cli._cmd_approvals_pending_latency,
            _ns(older_than="24h"),
        )
        assert "No engines have PENDING actions older than 24h" in out

    def test_invalid_older_than_exits_1(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_pending_latency,
            _ns(older_than="bogus"),
        )
        assert code == 1
        assert "Invalid --older-than" in out

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_pending(q, "e", count=2)
        out, _ = _capture(
            cli._cmd_approvals_pending_latency, _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert data[0]["engine"] == "e"
        assert data[0]["pending_count"] == 2
        assert "oldest_age_seconds" in data[0]
        assert "median_age_seconds" in data[0]
        assert "mean_age_seconds" in data[0]

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_approvals_pending_latency, _ns(json=True),
        )
        assert json.loads(out) == []

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        with patch.object(
            isolated_state["queue"], "pending_latency_stats",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_pending_latency, _ns(),
            )
        assert code == 0
        assert "No engines have PENDING actions" in out
