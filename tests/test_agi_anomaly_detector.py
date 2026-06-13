"""Tests for engines.agi_anomaly_detector — W963-57."""
from __future__ import annotations

import time

from engines.agi_anomaly_detector import (
    AgiAnomalyDetectorEngine,
)
from engines.agi_anomaly_detector.detector import (
    Anomaly,
    AnomalyReport,
    _build_headline,
    _build_next_action,
    _mad,
    _mode_verdict,
    detect,
)


# ── helpers ───────────────────────────────────────────────


def _snap(
    verdict="earning",
    profit=100.0,
    attr=50.0,
    orphans=0,
    ts_offset=0.0,
):
    return {
        "ts": time.time() - ts_offset,
        "verdict": verdict,
        "gross_profit": profit,
        "attribution_pct": attr,
        "orphan_action_count": orphans,
    }


# ── _mad ──────────────────────────────────────────────────


class TestMad:
    def test_empty(self):
        assert _mad([]) == 0.0

    def test_uniform_zero_mad(self):
        assert _mad([5.0, 5.0, 5.0]) == 0.0

    def test_simple(self):
        # median([1,2,3,4,5]) = 3; devs=[2,1,0,1,2]; median=1
        assert _mad([1.0, 2.0, 3.0, 4.0, 5.0]) == 1.0


# ── _mode_verdict ─────────────────────────────────────────


class TestModeVerdict:
    def test_empty(self):
        assert _mode_verdict([]) == "no_data"

    def test_simple_mode(self):
        snaps = [
            _snap(verdict="earning"),
            _snap(verdict="earning"),
            _snap(verdict="organic_only"),
        ]
        assert _mode_verdict(snaps) == "earning"


# ── detect() ──────────────────────────────────────────────


class TestDetect:
    def test_empty_no_anomalies(self):
        r = detect(snaps_override=[])
        assert r.sample_count == 0
        assert r.anomalies == []

    def test_too_few_for_flip(self):
        r = detect(snaps_override=[
            _snap(verdict="earning"),
            _snap(verdict="earning"),
        ])
        # min 3 for flip detection
        flips = [
            a for a in r.anomalies
            if a.type == "VERDICT_FLIP"
        ]
        assert flips == []

    def test_verdict_flip_critical(self):
        snaps = [
            _snap(verdict="attributed_loss"),  # latest
            _snap(verdict="earning"),
            _snap(verdict="earning"),
            _snap(verdict="earning"),
        ]
        r = detect(snaps_override=snaps)
        flips = [
            a for a in r.anomalies
            if a.type == "VERDICT_FLIP"
        ]
        assert len(flips) == 1
        assert flips[0].severity == "critical"

    def test_verdict_flip_info_when_recovering(self):
        snaps = [
            _snap(verdict="earning"),  # latest
            _snap(verdict="organic_only"),
            _snap(verdict="organic_only"),
            _snap(verdict="organic_only"),
        ]
        r = detect(snaps_override=snaps)
        flips = [
            a for a in r.anomalies
            if a.type == "VERDICT_FLIP"
        ]
        assert len(flips) == 1
        assert flips[0].severity == "info"

    def test_profit_outlier_drop_critical(self):
        snaps = [
            _snap(profit=-500.0),  # latest, huge drop
            _snap(profit=100.0),
            _snap(profit=110.0),
            _snap(profit=105.0),
            _snap(profit=120.0),
        ]
        r = detect(snaps_override=snaps)
        outs = [
            a for a in r.anomalies
            if a.type == "PROFIT_OUTLIER"
        ]
        assert len(outs) == 1
        assert outs[0].severity == "critical"
        assert outs[0].delta < 0

    def test_profit_outlier_spike_warn(self):
        snaps = [
            _snap(profit=10000.0),  # latest, huge spike
            _snap(profit=100.0),
            _snap(profit=110.0),
            _snap(profit=105.0),
            _snap(profit=120.0),
        ]
        r = detect(snaps_override=snaps)
        outs = [
            a for a in r.anomalies
            if a.type == "PROFIT_OUTLIER"
        ]
        assert len(outs) == 1
        assert outs[0].severity == "warn"

    def test_zero_mad_with_stable_history_fires_outlier(self):
        """W963-97 regression: pre-fix, mad==0 short-
        circuited and the function returned WITHOUT
        flagging anything. But mad=0 specifically means
        'history was perfectly stable' -- a zero-variance
        baseline. Any non-negligible deviation from that
        stable median IS the outlier we're meant to detect.
        Pre-fix: empire had $100 profit for 3 snapshots
        then $200 on snapshot 4 -- a 2x change -- NO
        anomaly fired because mad=0 masked it."""
        snaps = [
            _snap(profit=200.0),  # latest, deviates from 100 baseline
            _snap(profit=100.0),
            _snap(profit=100.0),
            _snap(profit=100.0),
        ]
        r = detect(snaps_override=snaps)
        outs = [
            a for a in r.anomalies
            if a.type == "PROFIT_OUTLIER"
        ]
        assert len(outs) == 1
        assert outs[0].severity == "warn"  # spike, not drop
        assert "stable history" in outs[0].description.lower()
        assert outs[0].delta == 100.0

    def test_zero_mad_with_stable_history_fires_critical_on_drop(self):
        """Symmetric case: drop on stable history -> critical."""
        snaps = [
            _snap(profit=-500.0),  # latest, big drop
            _snap(profit=100.0),
            _snap(profit=100.0),
            _snap(profit=100.0),
        ]
        r = detect(snaps_override=snaps)
        outs = [
            a for a in r.anomalies
            if a.type == "PROFIT_OUTLIER"
        ]
        assert len(outs) == 1
        assert outs[0].severity == "critical"

    def test_zero_mad_with_latest_matching_stays_quiet(self):
        """Sanity: when latest matches the stable baseline,
        no anomaly (no real deviation)."""
        snaps = [
            _snap(profit=100.0),  # latest matches baseline
            _snap(profit=100.0),
            _snap(profit=100.0),
            _snap(profit=100.0),
        ]
        r = detect(snaps_override=snaps)
        outs = [
            a for a in r.anomalies
            if a.type == "PROFIT_OUTLIER"
        ]
        assert outs == []

    def test_attribution_collapse(self):
        snaps = [
            _snap(attr=10.0),
            _snap(attr=80.0),
            _snap(attr=85.0),
            _snap(attr=75.0),
        ]
        r = detect(snaps_override=snaps)
        cols = [
            a for a in r.anomalies
            if a.type == "ATTRIBUTION_COLLAPSE"
        ]
        assert len(cols) == 1
        assert cols[0].severity == "critical"

    def test_attribution_spike(self):
        snaps = [
            _snap(attr=80.0),
            _snap(attr=10.0),
            _snap(attr=5.0),
            _snap(attr=15.0),
        ]
        r = detect(snaps_override=snaps)
        spk = [
            a for a in r.anomalies
            if a.type == "ATTRIBUTION_SPIKE"
        ]
        assert len(spk) == 1
        assert spk[0].severity == "info"

    def test_small_attribution_change_skipped(self):
        snaps = [
            _snap(attr=55.0),
            _snap(attr=50.0),
            _snap(attr=52.0),
            _snap(attr=48.0),
        ]
        r = detect(snaps_override=snaps)
        rel = [
            a for a in r.anomalies
            if "ATTRIBUTION" in a.type
        ]
        assert rel == []

    def test_orphan_burst(self):
        snaps = [
            _snap(orphans=15),
            _snap(orphans=1),
        ]
        r = detect(snaps_override=snaps)
        burst = [
            a for a in r.anomalies
            if a.type == "ORPHAN_BURST"
        ]
        assert len(burst) == 1
        assert burst[0].severity == "warn"
        assert burst[0].delta == 14.0

    def test_no_burst_when_already_high(self):
        snaps = [
            _snap(orphans=20),
            _snap(orphans=15),
        ]
        r = detect(snaps_override=snaps)
        burst = [
            a for a in r.anomalies
            if a.type == "ORPHAN_BURST"
        ]
        # Previous already > 2 -> not a burst
        assert burst == []

    def test_window_clamps(self):
        r = detect(window=999, snaps_override=[])
        assert r.window == 200
        r = detect(window=1, snaps_override=[])
        assert r.window == 3

    def test_critical_sorted_first(self):
        # Combined: profit drop (critical) + attribution
        # spike (info)
        snaps = [
            _snap(
                profit=-500.0, attr=80.0,
            ),
            _snap(profit=100.0, attr=10.0),
            _snap(profit=110.0, attr=5.0),
            _snap(profit=105.0, attr=15.0),
            _snap(profit=120.0, attr=12.0),
        ]
        r = detect(snaps_override=snaps)
        assert len(r.anomalies) >= 2
        assert r.anomalies[0].severity == "critical"


# ── headlines / next_action ───────────────────────────────


class TestHeadlines:
    def test_clean(self):
        r = AnomalyReport(window=14, sample_count=0)
        h = _build_headline(r)
        assert "Clean" in h

    def test_with_anomalies(self):
        r = AnomalyReport(window=14, sample_count=5)
        r.anomalies = [
            Anomaly(
                type="VERDICT_FLIP",
                severity="critical",
                delta=0,
                description="x",
            ),
            Anomaly(
                type="ORPHAN_BURST",
                severity="warn",
                delta=10,
                description="y",
            ),
        ]
        h = _build_headline(r)
        assert "1 critical" in h
        assert "1 warn" in h


class TestNextAction:
    def test_clean(self):
        r = AnomalyReport(window=14, sample_count=0)
        assert _build_next_action(r) == "All clear."

    def test_critical_present(self):
        r = AnomalyReport(window=14, sample_count=5)
        r.anomalies = [
            Anomaly(
                type="VERDICT_FLIP",
                severity="critical",
                delta=0, description="x",
            ),
        ]
        n = _build_next_action(r)
        assert "Critical" in n
        assert "engine alerts" in n

    def test_non_critical_only(self):
        r = AnomalyReport(window=14, sample_count=5)
        r.anomalies = [
            Anomaly(
                type="ORPHAN_BURST",
                severity="warn",
                delta=10, description="x",
            ),
        ]
        n = _build_next_action(r)
        assert "week-review" in n


# ── Pattern Q envelope ────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiAnomalyDetectorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiAnomalyDetectorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiAnomalyDetectorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiAnomalyDetectorEngine().run({
            "status": "fail", "error": "x",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiAnomalyDetectorEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_anomaly_detector"
        )

    def test_invalid_window_falls_back(self):
        r = AgiAnomalyDetectorEngine().run({
            "data": {"window": "abc"},
        })
        # 14 fallback, then clamped to >= 3 (still 14)
        assert r["data"]["window"] == 14
