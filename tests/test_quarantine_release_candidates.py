"""Tests for the quarantine-release candidate finder + CLI.

Symmetric to test_auto_approve_candidates.py (PR #164). Where
that one says "engines safe to opt INTO auto-approve", this one
says "engines safe to release FROM effective quarantine".

A release candidate is an engine that:
  - is NOT exempt (exemptions never trigger quarantine to begin
    with)
  - is NOT already on the released list (operator already
    cleared it)
  - has all-time negative_ratio ≥ MAX_NEGATIVE_RATIO (would be
    quarantined if not for exempt/released)
  - has recent_window negative_ratio < MAX_NEGATIVE_RATIO with
    ≥ MIN_OUTCOMES_OBSERVED outcomes in the window
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
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"data_dir": tmp_path, "queue": fresh}
    fresh._conn.close()


def _seed(q, *, engine, positive, negative=0, days_ago=0):
    """Seed outcomes, optionally backdating them to ``days_ago``."""
    now_offset = time.time() - days_ago * 86400 if days_ago else None
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        src = f"p{engine}_{days_ago}_{i}_{time.time_ns()}"
        q.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={}, source_event=src,
        )
        if now_offset is not None:
            q._conn.execute(
                "UPDATE action_outcomes SET recorded_at=? "
                "WHERE source_event=?", (now_offset, src),
            )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        src = f"n{engine}_{days_ago}_{i}_{time.time_ns()}"
        q.record_outcome(
            a.id, topic="refunds/create", polarity="negative",
            metrics={}, source_event=src,
        )
        if now_offset is not None:
            q._conn.execute(
                "UPDATE action_outcomes SET recorded_at=? "
                "WHERE source_event=?", (now_offset, src),
            )
    if now_offset is not None:
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
    defaults = dict(since="7d", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── find_release_candidates() ─────────────────────────────────


class TestFindReleaseCandidates:

    def test_empty_state_returns_empty(self, isolated_state):
        from core.approval.quarantine import find_release_candidates
        assert find_release_candidates(isolated_state["queue"]) == []

    def test_recovered_engine_is_candidate(self, isolated_state):
        """Engine with 30 old negative + 25 fresh positive →
        all-time looks bad, recent looks great → candidate."""
        from core.approval.quarantine import find_release_candidates
        q = isolated_state["queue"]
        _seed(q, engine="recovering", positive=0, negative=30, days_ago=10)
        _seed(q, engine="recovering", positive=25, negative=0)
        cands = find_release_candidates(q)
        assert len(cands) == 1
        c = cands[0]
        assert c.engine == "recovering"
        assert c.all_time_negative_ratio > 0.5  # would quarantine
        assert c.recent_negative_ratio == 0.0   # recent is clean
        assert c.recent_polarised == 25
        assert c.all_time_polarised == 55

    def test_healthy_engine_not_candidate(self, isolated_state):
        """An engine that's NOT effectively quarantined doesn't
        need a release recommendation."""
        from core.approval.quarantine import find_release_candidates
        _seed(
            isolated_state["queue"], engine="healthy",
            positive=25, negative=0,
        )
        assert find_release_candidates(isolated_state["queue"]) == []

    def test_still_bad_engine_not_candidate(self, isolated_state):
        """All-time AND recent still bad → not recovered →
        no recommendation."""
        from core.approval.quarantine import find_release_candidates
        _seed(
            isolated_state["queue"], engine="stillbad",
            positive=5, negative=25,
        )
        assert find_release_candidates(isolated_state["queue"]) == []

    def test_exempt_engine_excluded(self, isolated_state):
        """Exempted engines never quarantine → don't need
        release recommendations."""
        from core.approval.quarantine import (
            exempt_engine, find_release_candidates,
        )
        q = isolated_state["queue"]
        _seed(q, engine="returns", positive=0, negative=30, days_ago=10)
        _seed(q, engine="returns", positive=25, negative=0)
        exempt_engine("returns")
        assert find_release_candidates(q) == []

    def test_already_released_engine_excluded(self, isolated_state):
        """Already-released engines don't need recommendations
        — the operator already cleared them."""
        from core.approval.quarantine import (
            find_release_candidates, release_engine,
        )
        q = isolated_state["queue"]
        _seed(q, engine="cleared", positive=0, negative=30, days_ago=10)
        _seed(q, engine="cleared", positive=25, negative=0)
        release_engine("cleared")
        assert find_release_candidates(q) == []

    def test_insufficient_recent_history_excluded(
        self, isolated_state,
    ):
        """Recent recovery looks clean but with only 5 outcomes —
        not enough signal to recommend release."""
        from core.approval.quarantine import find_release_candidates
        q = isolated_state["queue"]
        _seed(q, engine="small_rec", positive=0, negative=30, days_ago=10)
        _seed(q, engine="small_rec", positive=5, negative=0)
        assert find_release_candidates(q) == []

    def test_recent_window_filters_out_old(self, isolated_state):
        """Outcomes outside the recent window don't count toward
        the recent-window stats. With 30 fresh negative inside
        the default 7d window, recent ratio stays bad even with
        fresh positives backdated to outside the window."""
        from core.approval.quarantine import find_release_candidates
        q = isolated_state["queue"]
        # Effectively quarantined: 30 old negatives
        _seed(q, engine="x", positive=0, negative=30, days_ago=30)
        # Fresh "improvement" but BACKDATED outside the 7d window
        _seed(q, engine="x", positive=25, negative=0, days_ago=14)
        # Inside-window: only 5 fresh negatives → recent ratio
        # is bad AND insufficient anyway
        _seed(q, engine="x", positive=0, negative=5)
        assert find_release_candidates(q) == []

    def test_custom_recent_window(self, isolated_state):
        """Operator can shrink the window via recent_seconds —
        catches recoveries that wouldn't show up under the
        default 7d."""
        from core.approval.quarantine import find_release_candidates
        q = isolated_state["queue"]
        _seed(q, engine="x", positive=0, negative=30, days_ago=30)
        # 25 positive 5 days ago — inside 7d, also inside 3d? no,
        # outside 3d
        _seed(q, engine="x", positive=25, negative=0, days_ago=5)
        # Default 7d window → recovered
        cands_7d = find_release_candidates(q)
        assert len(cands_7d) == 1
        # 3d window → outcome outside window → not recovered
        cands_3d = find_release_candidates(q, recent_seconds=3 * 86400)
        assert cands_3d == []

    def test_sorted_by_recent_polarised_desc(self, isolated_state):
        """Cleanest, deepest recoveries surface first.

        Both engines must STAY effectively quarantined even after
        recent recovery — i.e. all-time negative ratio must remain
        ≥ MAX_NEGATIVE_RATIO (0.50). 200 old negatives + 100 recent
        positives keeps A at 200/300 ≈ 0.67. 50 old + 25 recent
        keeps B at 50/75 ≈ 0.67."""
        from core.approval.quarantine import find_release_candidates
        q = isolated_state["queue"]
        # Engine A: 200 old neg + 100 fresh positive (deep recovery
        # window, still quarantined all-time)
        _seed(q, engine="a", positive=0, negative=200, days_ago=10)
        _seed(q, engine="a", positive=100, negative=0)
        # Engine B: 50 old neg + 25 fresh positive (lighter recovery)
        _seed(q, engine="b", positive=0, negative=50, days_ago=10)
        _seed(q, engine="b", positive=25, negative=0)
        cands = find_release_candidates(q)
        engines = [c.engine for c in cands]
        assert engines == ["a", "b"]

    def test_stats_lookup_failure_returns_empty(self, isolated_state):
        from core.approval.quarantine import find_release_candidates
        with patch.object(
            isolated_state["queue"], "all_engine_outcome_stats",
            side_effect=RuntimeError("db lock"),
        ):
            assert find_release_candidates(
                isolated_state["queue"],
            ) == []


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_prints_friendly_message(
        self, cli, isolated_state,
    ):
        out, code = _capture(
            cli._cmd_approvals_release_candidates, _ns(),
        )
        assert code == 0
        assert "No quarantine-release candidates" in out
        assert "7d" in out  # default window mentioned

    def test_table_view_lists_candidates(
        self, cli, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed(q, engine="recovering", positive=0, negative=30, days_ago=10)
        _seed(q, engine="recovering", positive=25, negative=0)
        out, _ = _capture(
            cli._cmd_approvals_release_candidates, _ns(),
        )
        assert "Quarantine-release candidates" in out
        assert "recovering" in out
        # Help footer points to release command
        assert "quarantine --release" in out

    def test_json_view(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed(q, engine="recovering", positive=0, negative=30, days_ago=10)
        _seed(q, engine="recovering", positive=25, negative=0)
        out, _ = _capture(
            cli._cmd_approvals_release_candidates, _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        row = data[0]
        assert row["engine"] == "recovering"
        assert row["recent_negative_ratio"] == 0.0
        assert row["recent_polarised"] == 25
        assert row["all_time_polarised"] == 55

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_approvals_release_candidates, _ns(json=True),
        )
        assert json.loads(out) == []

    def test_custom_since_propagates(self, cli, isolated_state):
        """`--since 3d` should shrink the recent window — a
        recovery 5 days ago becomes invisible."""
        q = isolated_state["queue"]
        _seed(q, engine="x", positive=0, negative=30, days_ago=30)
        _seed(q, engine="x", positive=25, negative=0, days_ago=5)
        # Default 7d → candidate
        out_default, _ = _capture(
            cli._cmd_approvals_release_candidates, _ns(),
        )
        assert "x" in out_default
        # 3d → no candidate
        out_3d, _ = _capture(
            cli._cmd_approvals_release_candidates,
            _ns(since="3d"),
        )
        assert "No quarantine-release candidates" in out_3d

    def test_invalid_since_exits_1(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_release_candidates,
            _ns(since="bogus"),
        )
        assert code == 1
        assert "Invalid --since" in out

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        with patch(
            "core.approval.quarantine.find_release_candidates",
            side_effect=RuntimeError("scan broke"),
        ):
            out, code = _capture(
                cli._cmd_approvals_release_candidates, _ns(),
            )
        assert code == 0
        assert "No quarantine-release candidates" in out
