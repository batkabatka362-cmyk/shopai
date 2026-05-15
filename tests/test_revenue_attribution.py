"""Tests for ``revenue_attribution_stats`` + CLI surface.

Surfaces per-engine revenue attribution from matched outcomes,
broken down into gross / refunded / net (the existing
``engine_outcome_stats`` returns only a signed net total).

Three sort modes on the CLI: net (default), gross, per-positive.
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


def _seed_outcome(q, *, engine, polarity, revenue):
    """Single action + matched outcome with revenue tag."""
    a = q.enqueue(
        engine=engine, action_type="y", capability="z",
        params={}, narrative="",
    )
    q.approve(a.id, decided_by="op")
    q.attach_result(a.id, success=True, result={})
    q.record_outcome(
        a.id, topic="o", polarity=polarity,
        metrics={"revenue": revenue} if revenue is not None else {},
        source_event=f"e_{engine}_{polarity}_{a.id}",
    )


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
    defaults = dict(top=20, sort="net", json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ─── revenue_attribution_stats() ───────────────────────────────


class TestRevenueAttributionStats:

    def test_empty_state_returns_empty(self, isolated_state):
        q = isolated_state["queue"]
        assert q.revenue_attribution_stats() == {}

    def test_engine_without_outcomes_absent(self, isolated_state):
        """An engine with actions but no matched outcomes
        shouldn't appear — nothing to attribute."""
        q = isolated_state["queue"]
        a = q.enqueue(
            engine="dry", action_type="y", capability="z",
            params={}, narrative="",
        )
        q.approve(a.id, decided_by="op")
        assert q.revenue_attribution_stats() == {}

    def test_positive_revenue_lands_in_gross(self, isolated_state):
        q = isolated_state["queue"]
        for _ in range(3):
            _seed_outcome(q, engine="e", polarity="positive", revenue=100)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["gross_revenue"] == 300.0
        assert stats["e"]["refunded_revenue"] == 0.0
        assert stats["e"]["net_revenue"] == 300.0

    def test_negative_revenue_lands_in_refunded(self, isolated_state):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=100)
        _seed_outcome(q, engine="e", polarity="negative", revenue=30)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["gross_revenue"] == 100.0
        assert stats["e"]["refunded_revenue"] == 30.0
        assert stats["e"]["net_revenue"] == 70.0

    def test_net_can_be_negative(self, isolated_state):
        """Refunds can exceed gross — net goes negative."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=10)
        _seed_outcome(q, engine="e", polarity="negative", revenue=50)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["net_revenue"] == -40.0

    def test_neutral_polarity_excluded(self, isolated_state):
        """Neutral outcomes don't carry revenue attribution."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=100)
        _seed_outcome(q, engine="e", polarity="neutral", revenue=999)
        stats = q.revenue_attribution_stats()
        # The neutral row didn't affect gross/refunded/counts
        assert stats["e"]["gross_revenue"] == 100.0
        assert stats["e"]["refunded_revenue"] == 0.0
        assert stats["e"]["positive_outcomes"] == 1
        assert stats["e"]["negative_outcomes"] == 0

    def test_revenue_per_positive_outcome(self, isolated_state):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=80)
        _seed_outcome(q, engine="e", polarity="positive", revenue=120)
        stats = q.revenue_attribution_stats()
        # (80+120)/2 = 100
        assert stats["e"]["revenue_per_positive_outcome"] == 100.0

    def test_revenue_per_positive_none_when_no_positives(
        self, isolated_state,
    ):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="negative", revenue=50)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["revenue_per_positive_outcome"] is None

    def test_missing_metrics_treated_as_zero(self, isolated_state):
        """An outcome without a revenue metric contributes 0 —
        not a crash."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=None)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["gross_revenue"] == 0.0
        assert stats["e"]["positive_outcomes"] == 1

    def test_multiple_engines_separate(self, isolated_state):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="a", polarity="positive", revenue=100)
        _seed_outcome(q, engine="b", polarity="positive", revenue=200)
        stats = q.revenue_attribution_stats()
        assert stats["a"]["gross_revenue"] == 100.0
        assert stats["b"]["gross_revenue"] == 200.0

    def test_counts_match_revenue_attribution(self, isolated_state):
        """positive_outcomes + negative_outcomes track the
        actual outcome rows, not the action count."""
        q = isolated_state["queue"]
        for _ in range(3):
            _seed_outcome(q, engine="e", polarity="positive", revenue=10)
        for _ in range(2):
            _seed_outcome(q, engine="e", polarity="negative", revenue=5)
        stats = q.revenue_attribution_stats()
        assert stats["e"]["positive_outcomes"] == 3
        assert stats["e"]["negative_outcomes"] == 2


# ─── CLI ───────────────────────────────────────────────────────


class TestCli:

    def test_empty_state_friendly_message(self, cli, isolated_state):
        out, code = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(),
        )
        assert code == 0
        assert "No engines have matched outcomes" in out

    def test_lists_engines_with_revenue(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=100)
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(),
        )
        assert "Revenue by engine" in out
        assert "e" in out
        assert "100.00" in out

    def test_sort_net_default(self, cli, isolated_state):
        """Default sort = net_revenue desc."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="low_net", polarity="positive", revenue=10)
        _seed_outcome(q, engine="high_net", polarity="positive", revenue=1000)
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(),
        )
        high_pos = out.find("high_net")
        low_pos = out.find("low_net")
        assert 0 <= high_pos < low_pos

    def test_sort_gross_ignores_refunds(self, cli, isolated_state):
        """Engine A: gross 1000, refunded 800 → net 200.
        Engine B: gross 500, refunded 0 → net 500.
        --sort net puts B first; --sort gross puts A first."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="a_gross", polarity="positive", revenue=1000)
        _seed_outcome(q, engine="a_gross", polarity="negative", revenue=800)
        _seed_outcome(q, engine="b_net", polarity="positive", revenue=500)
        # Default (net) puts b first
        out_net, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(sort="net"),
        )
        assert out_net.find("b_net") < out_net.find("a_gross")
        # Gross sort puts a first
        out_gross, _ = _capture(
            cli._cmd_approvals_revenue_by_engine,
            _ns(sort="gross"),
        )
        assert out_gross.find("a_gross") < out_gross.find("b_net")

    def test_sort_per_positive(self, cli, isolated_state):
        """Per-positive sort: average impact when something
        good happens — independent of volume."""
        q = isolated_state["queue"]
        # high_volume: 10 × $50 → per_positive=$50
        for _ in range(10):
            _seed_outcome(
                q, engine="high_volume",
                polarity="positive", revenue=50,
            )
        # low_volume_high_value: 2 × $500 → per_positive=$500
        for _ in range(2):
            _seed_outcome(
                q, engine="low_volume_high_value",
                polarity="positive", revenue=500,
            )
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine,
            _ns(sort="per-positive"),
        )
        # low_volume_high_value has higher per-positive ($500)
        # so it sorts first
        high_value_pos = out.find("low_volume_high_value")
        high_volume_pos = out.find("high_volume")
        assert 0 <= high_value_pos < high_volume_pos

    def test_top_n_limits_rows(self, cli, isolated_state):
        q = isolated_state["queue"]
        for i in range(5):
            _seed_outcome(
                q, engine=f"e{i}", polarity="positive",
                revenue=10 * (i + 1),
            )
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(top=2),
        )
        # Only top 2 engines surface — match by engine ids "eN"
        # (header line starts with "engine" which is not eN)
        import re
        lines = [
            line for line in out.splitlines()
            if re.match(r"^\s+e\d\b", line)
        ]
        assert len(lines) == 2

    def test_json_mode(self, cli, isolated_state):
        q = isolated_state["queue"]
        _seed_outcome(q, engine="e", polarity="positive", revenue=100)
        _seed_outcome(q, engine="e", polarity="negative", revenue=30)
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(json=True),
        )
        data = json.loads(out)
        assert isinstance(data, list)
        e = data[0]
        assert e["engine"] == "e"
        assert e["gross_revenue"] == 100.0
        assert e["refunded_revenue"] == 30.0
        assert e["net_revenue"] == 70.0

    def test_json_empty_is_empty_array(self, cli, isolated_state):
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(json=True),
        )
        assert json.loads(out) == []

    def test_negative_net_renders(self, cli, isolated_state):
        """An engine with more refunds than gross should still
        render — operators want to see it as a warning."""
        q = isolated_state["queue"]
        _seed_outcome(q, engine="bad", polarity="positive", revenue=10)
        _seed_outcome(q, engine="bad", polarity="negative", revenue=50)
        out, _ = _capture(
            cli._cmd_approvals_revenue_by_engine, _ns(),
        )
        assert "bad" in out
        # -40.00 appears in the net column
        assert "-40.00" in out

    def test_queue_failure_renders_empty(self, cli, isolated_state):
        with patch.object(
            isolated_state["queue"],
            "revenue_attribution_stats",
            side_effect=RuntimeError("db lock"),
        ):
            out, code = _capture(
                cli._cmd_approvals_revenue_by_engine, _ns(),
            )
        assert code == 0
        assert "No engines have matched outcomes" in out
