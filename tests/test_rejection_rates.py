"""Tests for ``rejection_rate_stats`` + CLI surface.

Per-engine rejection rate — surfaces engines whose proposals
operators consistently veto (engine-misbehaviour signal).

Different from quarantine (PR #162) which fires on negative
OUTCOMES post-execute; this is the rejected-BEFORE-execute
signal.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


def _seed(q, engine, *, approved=0, rejected=0, executed=0, failed=0):
    """Seed a per-engine mix of decisions."""
    for _ in range(approved):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
    for _ in range(rejected):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.reject(a.id, decided_by="op")
    for _ in range(executed):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
    for _ in range(failed):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
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
    defaults = dict(min_decisions=5, threshold=None, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── rejection_rate_stats() ────────────────────────────────────


class TestRejectionRateStats:

    def test_empty_state_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        assert q.rejection_rate_stats() == {}

    def test_pending_only_engine_absent(self, isolated_state):
        q = isolated_state["queue"]
        q.enqueue(
            engine="pending", action_type="y", capability="z",
            params={}, narrative="",
        )
        assert q.rejection_rate_stats() == {}

    def test_all_approved_engine_zero_rejection(self, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "clean", approved=10)
        stats = q.rejection_rate_stats()
        assert stats["clean"]["decided_count"] == 10
        assert stats["clean"]["approved_count"] == 10
        assert stats["clean"]["rejected_count"] == 0
        assert stats["clean"]["rejection_rate"] == 0.0

    def test_all_rejected_engine_one_rejection(self, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "bad", rejected=10)
        stats = q.rejection_rate_stats()
        assert stats["bad"]["rejection_rate"] == 1.0

    def test_mixed_engine_partial_rate(self, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "mixed", approved=2, rejected=8)
        stats = q.rejection_rate_stats()
        assert stats["mixed"]["decided_count"] == 10
        assert stats["mixed"]["rejected_count"] == 8
        assert stats["mixed"]["approved_count"] == 2
        assert stats["mixed"]["rejection_rate"] == 0.8

    def test_executed_counted_as_approved(self, isolated_state):
        """EXECUTED actions started as operator approves — they
        contribute to approved_count, not rejected_count."""
        q = isolated_state["queue"]
        _seed(q, "e", executed=5, rejected=5)
        stats = q.rejection_rate_stats()
        assert stats["e"]["approved_count"] == 5
        assert stats["e"]["rejected_count"] == 5
        assert stats["e"]["rejection_rate"] == 0.5

    def test_failed_counted_as_approved(self, isolated_state):
        """FAILED actions also started as operator approves —
        the failure is downstream, not a rejection."""
        q = isolated_state["queue"]
        _seed(q, "e", failed=5, rejected=5)
        stats = q.rejection_rate_stats()
        assert stats["e"]["approved_count"] == 5
        assert stats["e"]["rejected_count"] == 5

    def test_expired_excluded(self, isolated_state):
        """EXPIRED isn't an operator decision — the sweeper
        TTL'd it. Excluded from the rate."""
        import time
        q = isolated_state["queue"]
        # Seed normal decisions
        _seed(q, "e", approved=3, rejected=2)
        # Force-expire one
        a = q.enqueue(
            engine="e", action_type="y", capability="z",
            params={}, narrative="",
        )
        q._conn.execute(
            "UPDATE pending_actions SET proposed_at=? WHERE id=?",
            (time.time() - 86400, a.id),
        )
        q._conn.commit()
        q.expire_stale(max_age_seconds=60)
        stats = q.rejection_rate_stats()
        # Still 5 decided, not 6 (expired excluded)
        assert stats["e"]["decided_count"] == 5

    def test_multiple_engines_separate(self, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "good", approved=10)
        _seed(q, "bad", rejected=10)
        stats = q.rejection_rate_stats()
        assert stats["good"]["rejection_rate"] == 0.0
        assert stats["bad"]["rejection_rate"] == 1.0


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_friendly_message(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        assert code == 0
        assert "No engines with at least 5" in out

    def test_min_decisions_filter(self, cli, isolated_state):
        """An engine with only 3 decisions falls below default
        min_decisions=5 and is hidden."""
        q = isolated_state["queue"]
        _seed(q, "small", approved=1, rejected=2)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        assert "small" not in out

    def test_min_decisions_explicit_low(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "small", approved=1, rejected=2)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates,
            _ns(min_decisions=1),
        )
        assert "small" in out

    def test_threshold_filter(self, cli, isolated_state):
        """--threshold 0.5 hides engines below the rate."""
        q = isolated_state["queue"]
        _seed(q, "low_reject", approved=9, rejected=1)
        _seed(q, "high_reject", approved=2, rejected=8)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates,
            _ns(threshold=0.5),
        )
        assert "high_reject" in out
        assert "low_reject" not in out

    def test_high_rejection_sorts_first(self, cli, isolated_state):
        """Worst offenders surface at the top (triage UX)."""
        q = isolated_state["queue"]
        _seed(q, "z_clean", approved=10)
        _seed(q, "a_bad", approved=2, rejected=8)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        bad_pos = out.find("a_bad")
        clean_pos = out.find("z_clean")
        # bad surfaces first despite alphabetical position
        assert 0 <= bad_pos < clean_pos

    def test_alert_banner_for_majority_rejected(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed(q, "bad", approved=2, rejected=8)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        assert "ALERT" in out
        # Help footer surfaces the rejected-list command
        assert "approvals recent rejected" in out

    def test_no_alert_when_no_majority_rejected(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed(q, "ok", approved=8, rejected=2)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        assert "ALERT" not in out

    def test_bang_prefix_on_majority_rejected_row(
        self, cli, isolated_state,
    ):
        """Grep-friendly: each majority-rejected row starts
        with '!'."""
        q = isolated_state["queue"]
        _seed(q, "bad", approved=2, rejected=8)
        _seed(q, "ok", approved=8, rejected=2)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(),
        )
        for line in out.splitlines():
            if "bad" in line and "8" in line:
                assert line.startswith("!")
            if "ok" in line and "2" in line and "rate" not in line:
                assert not line.startswith("!")

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, "e", approved=5, rejected=5)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(json=True),
        )
        data = json.loads(out)
        assert data[0]["engine"] == "e"
        assert data[0]["decided_count"] == 10
        assert data[0]["rejection_rate"] == 0.5

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates, _ns(json=True),
        )
        assert json.loads(out) == []

    def test_threshold_empty_friendly_message(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed(q, "low", approved=9, rejected=1)
        out, _ = _capture(
            cli._cmd_approvals_rejection_rates,
            _ns(threshold=0.5),
        )
        assert "No engines with rejection_rate >= 0.5" in out

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        with patch.object(
            isolated_state["queue"], "rejection_rate_stats",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_rejection_rates, _ns(),
            )
        assert code == 0
        assert "No engines" in out
