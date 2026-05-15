"""Tests for the auto-approve candidate finder + CLI surface.

The finder scans engines with outcome history and returns those
that would pass the auto-approve OUTCOME guardrails (history +
ratio) if added to the allowlist. The CLI surfaces them as a
recommendation to drive operator adoption.

Confidence isn't checked here — that's per-action, not per-engine.
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
    monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield {"data_dir": tmp_path, "queue": fresh}
    fresh._conn.close()


def _seed(q, *, engine, positive, negative=0):
    for i in range(positive):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="orders/create", polarity="positive",
            metrics={}, source_event=f"p{engine}_{i}",
        )
    for i in range(negative):
        a = q.enqueue(
            engine=engine, action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        q.attach_result(a.id, success=True, result={})
        q.record_outcome(
            a.id, topic="refunds/create", polarity="negative",
            metrics={}, source_event=f"n{engine}_{i}",
        )


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── find_candidates() ─────────────────────────────────────────


class TestFindCandidates:

    def test_empty_state_returns_empty(self, isolated_state):
        from core.approval.auto_approve import find_candidates
        candidates = find_candidates(isolated_state["queue"])
        assert candidates == []

    def test_clean_engine_with_full_history_is_candidate(
        self, isolated_state,
    ):
        from core.approval.auto_approve import find_candidates
        _seed(isolated_state["queue"], engine="cart_recovery", positive=25)
        candidates = find_candidates(isolated_state["queue"])
        assert len(candidates) == 1
        c = candidates[0]
        assert c.engine == "cart_recovery"
        assert c.outcome_ratio == 1.0
        assert c.positive == 25
        assert c.negative == 0
        assert c.total_polarised == 25

    def test_low_ratio_engine_excluded(self, isolated_state):
        """An engine with 30 outcomes but only 60% positive
        doesn't make the cut (below 0.85 default threshold)."""
        from core.approval.auto_approve import find_candidates
        _seed(isolated_state["queue"], engine="bad", positive=18, negative=12)
        candidates = find_candidates(isolated_state["queue"])
        assert all(c.engine != "bad" for c in candidates)

    def test_insufficient_history_excluded(self, isolated_state):
        """5 outcomes is below the 20 default floor."""
        from core.approval.auto_approve import find_candidates
        _seed(isolated_state["queue"], engine="new", positive=5)
        candidates = find_candidates(isolated_state["queue"])
        assert candidates == []

    def test_borderline_ratio_passes(self, isolated_state):
        """85% positive (the exact threshold) passes — the
        comparator is >=, not >."""
        from core.approval.auto_approve import find_candidates
        _seed(
            isolated_state["queue"], engine="border",
            positive=17, negative=3,
        )
        candidates = find_candidates(isolated_state["queue"])
        assert len(candidates) == 1
        # 17/20 = 0.85 exactly
        assert candidates[0].outcome_ratio == 0.85

    def test_already_allowlisted_engines_excluded(self, isolated_state):
        """If the operator already opted an engine in, it's not
        a candidate — the recommendation surface is for adoption,
        not inventory."""
        from core.approval.auto_approve import enable_engine, find_candidates
        _seed(isolated_state["queue"], engine="cart_recovery", positive=25)
        _seed(isolated_state["queue"], engine="loyalty", positive=25)
        enable_engine("cart_recovery")
        candidates = find_candidates(isolated_state["queue"])
        assert {c.engine for c in candidates} == {"loyalty"}

    def test_sorted_by_history_then_ratio_desc(self, isolated_state):
        """Highest history count first; ties break on highest
        ratio. Gives operators the most-trusted recommendations
        at the top."""
        from core.approval.auto_approve import find_candidates
        _seed(
            isolated_state["queue"], engine="lots_perfect",
            positive=100,
        )
        _seed(
            isolated_state["queue"], engine="some_great",
            positive=30, negative=2,
        )
        _seed(
            isolated_state["queue"], engine="some_good",
            positive=20, negative=3,
        )
        candidates = find_candidates(isolated_state["queue"])
        engines = [c.engine for c in candidates]
        # Order: lots_perfect (100 pol), some_great (32), some_good (23)
        assert engines == ["lots_perfect", "some_great", "some_good"]

    def test_stats_lookup_failure_returns_empty(self, isolated_state):
        """``all_engine_outcome_stats`` raising must not crash
        the finder — return empty so the CLI prints "no
        candidates" rather than 500'ing."""
        from core.approval.auto_approve import find_candidates
        with patch.object(
            isolated_state["queue"], "all_engine_outcome_stats",
            side_effect=RuntimeError("db lock"),
        ):
            assert find_candidates(isolated_state["queue"]) == []


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_prints_friendly_message(
        self, cli, isolated_state,
    ):
        out = _capture(
            cli._cmd_approvals_auto_candidates, _ns(),
        )
        assert "No auto-approve candidates" in out

    def test_table_view_lists_candidates(
        self, cli, isolated_state,
    ):
        _seed(
            isolated_state["queue"], engine="cart_recovery",
            positive=25,
        )
        out = _capture(
            cli._cmd_approvals_auto_candidates, _ns(),
        )
        assert "Auto-approve candidates" in out
        assert "cart_recovery" in out
        # The supporting numbers appear
        assert "25" in out  # positive + total_polarised
        # Help footer points operators at the enable command
        assert "auto-config --enable" in out

    def test_json_view(self, cli, isolated_state):
        _seed(
            isolated_state["queue"], engine="cart_recovery",
            positive=25,
        )
        out = _capture(
            cli._cmd_approvals_auto_candidates, _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        c = data[0]
        assert c["engine"] == "cart_recovery"
        assert c["positive"] == 25
        assert c["negative"] == 0
        assert c["total_polarised"] == 25
        assert c["outcome_ratio"] == 1.0

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out = _capture(
            cli._cmd_approvals_auto_candidates, _ns(json=True),
        )
        assert json.loads(out) == []

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        from core.approval.auto_approve import find_candidates
        with patch(
            "core.approval.auto_approve.find_candidates",
            side_effect=RuntimeError("scan broke"),
        ):
            out = _capture(
                cli._cmd_approvals_auto_candidates, _ns(),
            )
        assert "No auto-approve candidates" in out
