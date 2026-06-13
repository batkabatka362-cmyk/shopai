"""Tests for engines.agi_recommend_streak — W963-70."""
from __future__ import annotations

from engines.agi_recommend_streak import (
    AgiRecommendStreakEngine,
)
from engines.agi_recommend_streak.detector import (
    _build_headline,
    _build_next_action,
    _count_anomaly_streak,
    _count_loss_streak,
    _count_no_data_streak,
    _severity_for,
    StreakReport,
    detect_streaks,
)


def _snap(
    verdict="earning",
    critical_anomaly_count=0,
    orphan_action_count=0,
):
    return {
        "verdict": verdict,
        "critical_anomaly_count": critical_anomaly_count,
        "orphan_action_count": orphan_action_count,
    }


# ── _severity_for ─────────────────────────────────────────


class TestSeverity:
    def test_below_threshold_info(self):
        assert _severity_for(1, 3) == "info"
        assert _severity_for(2, 3) == "info"

    def test_at_threshold_warn(self):
        assert _severity_for(3, 3) == "warn"
        assert _severity_for(5, 3) == "warn"

    def test_double_threshold_critical(self):
        assert _severity_for(6, 3) == "critical"
        assert _severity_for(100, 3) == "critical"

    def test_zero_is_info(self):
        assert _severity_for(0, 3) == "info"


# ── _count_*_streak ───────────────────────────────────────


class TestCountLossStreak:
    def test_empty(self):
        assert _count_loss_streak([]) == 0

    def test_no_stress(self):
        assert _count_loss_streak([
            _snap("earning"),
            _snap("earning"),
        ]) == 0

    def test_recent_three(self):
        assert _count_loss_streak([
            _snap("attributed_loss"),
            _snap("organic_only"),
            _snap("attributed_loss"),
            _snap("earning"),  # breaks streak
            _snap("attributed_loss"),  # not counted
        ]) == 3

    def test_first_non_stress_breaks(self):
        assert _count_loss_streak([
            _snap("earning"),  # latest, no stress
            _snap("attributed_loss"),
        ]) == 0


class TestCountNoDataStreak:
    def test_consecutive_no_data(self):
        assert _count_no_data_streak([
            _snap("no_data"),
            _snap("no_data"),
            _snap("earning"),
        ]) == 2

    def test_no_data_broken(self):
        assert _count_no_data_streak([
            _snap("earning"),
            _snap("no_data"),
            _snap("no_data"),
        ]) == 0


class TestCountAnomalyStreak:
    def test_critical_anomaly(self):
        assert _count_anomaly_streak([
            _snap(critical_anomaly_count=2),
            _snap(critical_anomaly_count=1),
            _snap(critical_anomaly_count=0),
        ]) == 2

    def test_orphan_threshold(self):
        assert _count_anomaly_streak([
            _snap(orphan_action_count=10),
            _snap(orphan_action_count=4),  # < 5 breaks
        ]) == 1

    def test_anomaly_or_orphan(self):
        assert _count_anomaly_streak([
            _snap(critical_anomaly_count=1),
            _snap(orphan_action_count=8),
            _snap(),  # clean
        ]) == 2

    def test_garbage_breaks(self):
        # Non-int values short-circuit the loop
        snaps = [
            {"critical_anomaly_count": "two"},
        ]
        assert _count_anomaly_streak(snaps) == 0


# ── _build_headline / _build_next_action ──────────────────


class TestHeadline:
    def test_clean(self):
        r = StreakReport()
        h = _build_headline(r, 3)
        assert "No persistent" in h
        assert r.attention_needed is False

    def test_warn_loss_dominates(self):
        r = StreakReport()
        r.loss_streak.count = 3
        r.loss_streak.severity = "warn"
        h = _build_headline(r, 3)
        assert "ATTENTION" in h
        assert "loss_streak" in h
        assert r.attention_needed is True
        assert r.top_streak == "loss_streak"

    def test_critical_outranks_warn(self):
        r = StreakReport()
        r.loss_streak.count = 3
        r.loss_streak.severity = "warn"
        r.no_data_streak.count = 6
        r.no_data_streak.severity = "critical"
        h = _build_headline(r, 3)
        assert r.top_streak == "no_data_streak"

    def test_higher_count_wins_tie_in_severity(self):
        r = StreakReport()
        r.loss_streak.count = 3
        r.loss_streak.severity = "warn"
        r.anomaly_streak.count = 4
        r.anomaly_streak.severity = "warn"
        _build_headline(r, 3)
        # Both warn -> higher count wins
        assert r.top_streak == "anomaly_streak"


class TestNextAction:
    def test_clean_no_action(self):
        r = StreakReport()
        assert "morning ritual" in _build_next_action(r)

    def test_loss_drill(self):
        r = StreakReport()
        r.attention_needed = True
        r.top_streak = "loss_streak"
        r.loss_streak.drill = "shopai roas"
        assert "roas" in _build_next_action(r)

    def test_no_data_drill(self):
        r = StreakReport()
        r.attention_needed = True
        r.top_streak = "no_data_streak"
        r.no_data_streak.drill = "shopai cycle status"
        assert "cycle status" in _build_next_action(r)

    def test_anomaly_drill(self):
        r = StreakReport()
        r.attention_needed = True
        r.top_streak = "anomaly_streak"
        r.anomaly_streak.drill = "shopai anomalies"
        assert "anomalies" in _build_next_action(r)


# ── detect_streaks ────────────────────────────────────────


class TestDetectStreaks:
    def test_no_snapshots(self):
        r = detect_streaks(snapshots_override=[])
        assert r.samples_scanned == 0
        assert r.attention_needed is False

    def test_clean_history(self):
        r = detect_streaks(snapshots_override=[
            _snap("earning"),
            _snap("earning"),
        ])
        assert r.attention_needed is False

    def test_loss_streak_warn(self):
        snaps = [
            _snap("attributed_loss"),
            _snap("attributed_loss"),
            _snap("organic_only"),
        ]
        r = detect_streaks(
            threshold_days=3,
            snapshots_override=snaps,
        )
        assert r.loss_streak.count == 3
        assert r.loss_streak.severity == "warn"
        assert r.attention_needed is True

    def test_loss_streak_critical(self):
        snaps = [_snap("attributed_loss")] * 7
        r = detect_streaks(
            threshold_days=3,
            snapshots_override=snaps,
        )
        assert r.loss_streak.severity == "critical"

    def test_threshold_clamps_to_one(self):
        r = detect_streaks(
            threshold_days=0,
            snapshots_override=[_snap("earning")],
        )
        # min clamp keeps at 1; no streaks though
        assert r.samples_scanned == 1


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiRecommendStreakEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiRecommendStreakEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiRecommendStreakEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiRecommendStreakEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiRecommendStreakEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_recommend_streak"
        )

    def test_invalid_threshold_falls_back(self):
        r = AgiRecommendStreakEngine().run({
            "data": {"threshold_days": "abc"},
        })
        # Falls back to default + clamps to >= 1
        assert r["status"] == "success"
