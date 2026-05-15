"""Tests for ``decision_latency_stats`` + CLI surface.

Per-engine aggregate of decision latency (decided_at -
proposed_at). Complement to pending-latency (PR #168).
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


def _backdate_proposed(q, action_id, seconds_ago):
    q._conn.execute(
        "UPDATE pending_actions SET proposed_at = ? WHERE id = ?",
        (time.time() - seconds_ago, action_id),
    )
    q._conn.commit()


def _seed_decided(
    q, engine, count, *, age_seconds=0, transition="approve",
):
    """Seed N actions, backdate proposed_at, then transition."""
    for _ in range(count):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        if age_seconds:
            _backdate_proposed(q, a.id, age_seconds)
        if transition == "approve":
            q.approve(a.id, decided_by="op")
        elif transition == "reject":
            q.reject(a.id, decided_by="op")
        elif transition == "execute":
            q.approve(a.id, decided_by="op")
            q.attach_result(a.id, success=True, result={})
        elif transition == "fail":
            q.approve(a.id, decided_by="op")
            q.attach_result(a.id, success=False, result={})


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
    defaults = dict(status="default", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── decision_latency_stats() ──────────────────────────────────


class TestDecisionLatencyStats:

    def test_empty_state_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        assert q.decision_latency_stats() == {}

    def test_pending_only_engine_absent(self, isolated_state):
        """Engines whose actions never moved past PENDING aren't
        in the result — there's no decision to measure."""
        q = isolated_state["queue"]
        q.enqueue(
            engine="pending_only", action_type="y", capability="z",
            params={}, narrative="",
        )
        assert q.decision_latency_stats() == {}

    def test_fast_decision_low_latency(self, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "fast", count=3)
        stats = q.decision_latency_stats()
        assert stats["fast"]["decided_count"] == 3
        # Sub-second turnaround in tests
        assert stats["fast"]["median_seconds"] <= 1
        assert stats["fast"]["slowest_seconds"] <= 5

    def test_slow_decision_high_latency(self, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "slow", count=3, age_seconds=86400)
        stats = q.decision_latency_stats()
        # ~1 day, allow small slop
        assert stats["slow"]["median_seconds"] >= 86399
        assert stats["slow"]["median_seconds"] <= 86405

    def test_median_with_odd_count(self, isolated_state):
        q = isolated_state["queue"]
        # 3 actions with ages 10s, 100s, 1000s → median 100
        for age in (10, 100, 1000):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            _backdate_proposed(q, a.id, age)
            q.approve(a.id, decided_by="op")
        stats = q.decision_latency_stats()
        # Allow ±2s for test execution time
        assert 95 <= stats["e"]["median_seconds"] <= 105

    def test_median_with_even_count(self, isolated_state):
        q = isolated_state["queue"]
        for age in (10, 100, 200, 1000):
            a = q.enqueue(
                engine="e", action_type="y", capability="z",
                params={}, narrative="",
            )
            _backdate_proposed(q, a.id, age)
            q.approve(a.id, decided_by="op")
        stats = q.decision_latency_stats()
        # Mean of middle two: (100+200)/2 = 150
        assert 145 <= stats["e"]["median_seconds"] <= 155

    def test_includes_approved_and_rejected_by_default(
        self, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed_decided(q, "approver", count=2, transition="approve")
        _seed_decided(q, "rejecter", count=2, transition="reject")
        stats = q.decision_latency_stats()
        assert "approver" in stats
        assert "rejecter" in stats

    def test_executed_actions_counted(self, isolated_state):
        """attach_result transitions APPROVED→EXECUTED but
        doesn't touch decided_at — so EXECUTED rows still
        carry operator-click time and should be included."""
        q = isolated_state["queue"]
        _seed_decided(q, "e", count=2, transition="execute")
        stats = q.decision_latency_stats()
        assert "e" in stats
        assert stats["e"]["decided_count"] == 2

    def test_failed_actions_counted(self, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "e", count=2, transition="fail")
        stats = q.decision_latency_stats()
        assert "e" in stats

    def test_expired_excluded_by_default(self, isolated_state):
        """EXPIRED's decided_at reflects sweeper time, not
        operator click — exclude from the default set."""
        from core.approval.queue import ApprovalStatus
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="stale", action_type="y", capability="z",
            params={}, narrative="",
        )
        _backdate_proposed(q, a.id, 86400 * 30)
        expired = q.expire_stale(max_age_seconds=60)
        assert len(expired) == 1
        # Default call → no EXPIRED
        default_stats = q.decision_latency_stats()
        assert "stale" not in default_stats
        # Explicit EXPIRED → included
        explicit = q.decision_latency_stats(
            statuses=[ApprovalStatus.EXPIRED],
        )
        assert "stale" in explicit

    def test_explicit_status_subset(self, isolated_state):
        """Restrict to just one status."""
        from core.approval.queue import ApprovalStatus
        q = isolated_state["queue"]
        _seed_decided(q, "approver", count=2, transition="approve")
        _seed_decided(q, "rejecter", count=2, transition="reject")
        stats = q.decision_latency_stats(
            statuses=[ApprovalStatus.REJECTED],
        )
        assert "rejecter" in stats
        assert "approver" not in stats

    def test_empty_statuses_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "e", count=2)
        assert q.decision_latency_stats(statuses=[]) == {}


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_friendly_message(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_decision_latency, _ns(),
        )
        assert code == 0
        assert "No decided actions" in out

    def test_lists_engines(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "fast", count=3)
        _seed_decided(q, "slow", count=2, age_seconds=86400)
        out, _ = _capture(
            cli._cmd_approvals_decision_latency, _ns(),
        )
        assert "Decision latency" in out
        assert "fast" in out
        assert "slow" in out

    def test_slowest_median_sorts_first(self, cli, isolated_state):
        """Slowest median first — engines operators struggle with
        most surface at the top (matches triage UX)."""
        q = isolated_state["queue"]
        _seed_decided(q, "z_fast", count=3)
        _seed_decided(q, "a_slow", count=3, age_seconds=86400)
        out, _ = _capture(
            cli._cmd_approvals_decision_latency, _ns(),
        )
        slow_pos = out.find("a_slow")
        fast_pos = out.find("z_fast")
        assert 0 <= slow_pos < fast_pos

    def test_status_filter_approved(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "approver", count=2, transition="approve")
        _seed_decided(q, "rejecter", count=2, transition="reject")
        out, _ = _capture(
            cli._cmd_approvals_decision_latency,
            _ns(status="approved"),
        )
        assert "approver" in out
        assert "rejecter" not in out

    def test_status_all_includes_expired(self, cli, isolated_state):
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="expired_engine", action_type="y",
            capability="z", params={}, narrative="",
        )
        _backdate_proposed(q, a.id, 86400 * 30)
        q.expire_stale(max_age_seconds=60)
        # default → not present
        out_default, _ = _capture(
            cli._cmd_approvals_decision_latency, _ns(),
        )
        assert "expired_engine" not in out_default
        # all → present
        out_all, _ = _capture(
            cli._cmd_approvals_decision_latency,
            _ns(status="all"),
        )
        assert "expired_engine" in out_all

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_decided(q, "e", count=2)
        out, _ = _capture(
            cli._cmd_approvals_decision_latency,
            _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert data[0]["engine"] == "e"
        assert data[0]["decided_count"] == 2
        assert "slowest_seconds" in data[0]
        assert "median_seconds" in data[0]
        assert "mean_seconds" in data[0]

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_approvals_decision_latency,
            _ns(json=True),
        )
        assert json.loads(out) == []

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        with patch.object(
            isolated_state["queue"],
            "decision_latency_stats",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_decision_latency, _ns(),
            )
        assert code == 0
        assert "No decided actions" in out
