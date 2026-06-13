"""Tests for engines.agi_brief_diff — W963-68."""
from __future__ import annotations

import time

from engines.agi_brief_diff import AgiBriefDiffEngine
from engines.agi_brief_diff.differ import (
    BriefDiff,
    _build_drift_notes,
    _build_headline,
    _build_next_action,
    _classify_direction,
    _classify_verdict_change,
    compute_diff,
)


# ── helpers ───────────────────────────────────────────────


def _snap(
    verdict="earning",
    profit=100.0,
    attr=50.0,
    run_rate=400.0,
    trend="flat",
    ts_offset=0.0,
):
    return {
        "ts": time.time() - ts_offset,
        "verdict": verdict,
        "gross_profit": profit,
        "attribution_pct": attr,
        "monthly_run_rate": run_rate,
        "trend_verdict": trend,
    }


# ── _classify_verdict_change ──────────────────────────────


class TestClassifyVerdictChange:
    def test_no_change(self):
        assert _classify_verdict_change(
            "earning", "earning",
        ) == "no_change"

    def test_up(self):
        assert _classify_verdict_change(
            "organic_only", "earning",
        ) == "improved"

    def test_down(self):
        assert _classify_verdict_change(
            "earning", "attributed_loss",
        ) == "regressed"

    def test_no_data_to_earning_is_up(self):
        assert _classify_verdict_change(
            "no_data", "earning",
        ) == "improved"


# ── _classify_direction ───────────────────────────────────


def _make_diff(verdict_change, profit_delta):
    d = BriefDiff(
        sufficient=True,
        verdict_change=verdict_change,
        gross_profit_delta=profit_delta,
    )
    return d


class TestClassifyDirection:
    def test_improved_verdict_wins(self):
        d = _make_diff("improved", -100.0)  # ignored
        assert _classify_direction(d) == "improved"

    def test_regressed_verdict_wins(self):
        d = _make_diff("regressed", 100.0)
        assert _classify_direction(d) == "regressed"

    def test_unchanged_small_drift(self):
        d = _make_diff("no_change", 2.0)
        assert _classify_direction(d) == "unchanged"

    def test_unchanged_negative_small(self):
        d = _make_diff("no_change", -2.0)
        assert _classify_direction(d) == "unchanged"

    def test_significant_gain_improved(self):
        d = _make_diff("no_change", 50.0)
        assert _classify_direction(d) == "improved"

    def test_significant_drop_regressed(self):
        d = _make_diff("no_change", -50.0)
        assert _classify_direction(d) == "regressed"


# ── _build_drift_notes ────────────────────────────────────


class TestDriftNotes:
    def test_below_thresholds_silent(self):
        d = BriefDiff(
            gross_profit_delta=1.0,
            attribution_pct_delta=0.1,
            monthly_run_rate_delta=5.0,
            history_trend_previous="flat",
            history_trend_current="flat",
        )
        assert _build_drift_notes(d) == []

    def test_profit_threshold(self):
        d = BriefDiff(
            gross_profit_delta=10.0,
            history_trend_previous="flat",
            history_trend_current="flat",
        )
        notes = _build_drift_notes(d)
        assert any("gross_profit" in n for n in notes)

    def test_trend_change(self):
        d = BriefDiff(
            history_trend_previous="flat",
            history_trend_current="improving",
        )
        notes = _build_drift_notes(d)
        assert any("trend" in n for n in notes)


# ── _build_headline / _build_next_action ──────────────────


class TestHeadline:
    def test_insufficient(self):
        d = BriefDiff(sufficient=False)
        assert "at least 2" in _build_headline(d)

    def test_improved_with_verdict_shift(self):
        d = BriefDiff(
            sufficient=True,
            previous_verdict="organic_only",
            current_verdict="earning",
            verdict_change="improved",
            direction="improved",
            gross_profit_delta=100.0,
        )
        assert "IMPROVED" in _build_headline(d)

    def test_improved_without_verdict_shift(self):
        d = BriefDiff(
            sufficient=True,
            previous_verdict="earning",
            current_verdict="earning",
            verdict_change="no_change",
            direction="improved",
            gross_profit_delta=20.0,
        )
        h = _build_headline(d)
        assert "IMPROVED" in h
        assert "+$20" in h

    def test_regressed(self):
        d = BriefDiff(
            sufficient=True,
            previous_verdict="earning",
            current_verdict="attributed_loss",
            verdict_change="regressed",
            direction="regressed",
        )
        assert "REGRESSED" in _build_headline(d)

    def test_unchanged(self):
        d = BriefDiff(
            sufficient=True,
            previous_verdict="earning",
            current_verdict="earning",
            verdict_change="no_change",
            direction="unchanged",
        )
        h = _build_headline(d)
        assert "Unchanged" in h

    def test_regressed_profit_drop_renders_minus_dollar(self):
        """W963-93 regression test: pre-fix REGRESSED
        branch showed $-50 (sign after dollar). Now -$50."""
        d = BriefDiff(
            sufficient=True,
            previous_verdict="earning",
            current_verdict="earning",
            verdict_change="no_change",
            direction="regressed",
            gross_profit_delta=-80.0,
        )
        h = _build_headline(d)
        assert "-$80" in h
        assert "$-80" not in h

    def test_improved_profit_gain_renders_plus_dollar(self):
        d = BriefDiff(
            sufficient=True,
            previous_verdict="earning",
            current_verdict="earning",
            verdict_change="no_change",
            direction="improved",
            gross_profit_delta=120.0,
        )
        h = _build_headline(d)
        assert "+$120" in h


class TestNextAction:
    def test_insufficient(self):
        d = BriefDiff(sufficient=False)
        assert "morning-brief --record" in _build_next_action(d)

    def test_regressed(self):
        d = BriefDiff(
            sufficient=True, direction="regressed",
        )
        n = _build_next_action(d)
        assert "anomalies" in n
        assert "action-critic" in n

    def test_improved(self):
        d = BriefDiff(
            sufficient=True, direction="improved",
        )
        n = _build_next_action(d)
        assert "next-actions" in n

    def test_unchanged(self):
        d = BriefDiff(
            sufficient=True, direction="unchanged",
        )
        n = _build_next_action(d)
        assert "morning-brief" in n


# ── compute_diff ──────────────────────────────────────────


class TestComputeDiff:
    def test_no_snapshots(self):
        d = compute_diff(snapshots_override=[])
        assert d.samples_available == 0
        assert d.sufficient is False
        assert d.direction == "no_data"

    def test_one_snapshot(self):
        d = compute_diff(snapshots_override=[_snap()])
        assert d.samples_available == 1
        assert d.sufficient is False

    def test_two_snapshots_improved(self):
        snaps = [
            _snap(verdict="earning", profit=200.0),
            _snap(verdict="organic_only", profit=50.0),
        ]
        d = compute_diff(snapshots_override=snaps)
        assert d.sufficient is True
        assert d.previous_verdict == "organic_only"
        assert d.current_verdict == "earning"
        assert d.gross_profit_delta == 150.0
        assert d.direction == "improved"

    def test_two_snapshots_regressed(self):
        snaps = [
            _snap(verdict="attributed_loss", profit=-50.0),
            _snap(verdict="earning", profit=200.0),
        ]
        d = compute_diff(snapshots_override=snaps)
        assert d.direction == "regressed"
        assert d.gross_profit_delta == -250.0

    def test_two_snapshots_unchanged(self):
        snaps = [
            _snap(verdict="earning", profit=100.0),
            _snap(verdict="earning", profit=99.5),
        ]
        d = compute_diff(snapshots_override=snaps)
        assert d.direction == "unchanged"


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiBriefDiffEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiBriefDiffEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiBriefDiffEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiBriefDiffEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiBriefDiffEngine().run({})
        assert r["meta"]["engine"] == "agi_brief_diff"

    def test_data_has_direction(self):
        r = AgiBriefDiffEngine().run({})
        assert "direction" in r["data"]
