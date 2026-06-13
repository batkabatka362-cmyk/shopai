"""Tests for engines.confidence_calibrator — W963-39."""
from __future__ import annotations

from unittest.mock import patch

from engines.confidence_calibrator import (
    ConfidenceCalibratorEngine,
)
from engines.confidence_calibrator.calibrator import (
    EngineCalibration,
    _band_for,
    band_thresholds,
    calibrate,
)


# ── _band_for ──────────────────────────────────────────────


class TestBandFor:
    def test_insufficient_sample(self):
        assert _band_for(
            sample=2, positive_ratio=0.95, min_sample=5,
        ) == "unknown"

    def test_relaxed(self):
        assert _band_for(
            sample=10, positive_ratio=0.96, min_sample=5,
        ) == "relaxed"

    def test_standard(self):
        assert _band_for(
            sample=10, positive_ratio=0.85, min_sample=5,
        ) == "standard"

    def test_cautious(self):
        assert _band_for(
            sample=10, positive_ratio=0.70, min_sample=5,
        ) == "cautious"

    def test_blocked(self):
        assert _band_for(
            sample=10, positive_ratio=0.30, min_sample=5,
        ) == "blocked"

    def test_zero_ratio_blocked(self):
        assert _band_for(
            sample=10, positive_ratio=0.0, min_sample=5,
        ) == "blocked"

    def test_exact_threshold_relaxed(self):
        assert _band_for(
            sample=10, positive_ratio=0.95, min_sample=5,
        ) == "relaxed"

    def test_exact_threshold_standard(self):
        assert _band_for(
            sample=10, positive_ratio=0.80, min_sample=5,
        ) == "standard"


# ── band_thresholds ───────────────────────────────────────


class TestBandThresholds:
    def test_blocked_above_one(self):
        # Blocked threshold > 1.0 so it can never be matched
        t = band_thresholds()
        assert t["blocked"] > 1.0

    def test_relaxed_lowest(self):
        t = band_thresholds()
        assert t["relaxed"] < t["standard"] < t["cautious"]


# ── calibrate ──────────────────────────────────────────────


class TestCalibrate:
    def test_no_engines(self):
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
            return_value=[],
        ):
            r = calibrate()
        assert r.total_engines == 0
        assert r.calibrations == []

    def test_calibrates_each_engine(self):
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
            return_value=["a", "b", "c"],
        ), patch(
            "engines.confidence_calibrator.calibrator."
            "_engine_outcome_stats",
            side_effect=[
                (10, 0),     # a: 100% positive
                (8, 2),      # b: 80%
                (3, 7),      # c: 30%
            ],
        ):
            r = calibrate(min_sample=5)
        assert r.total_engines == 3
        bands = {c.engine: c.band for c in r.calibrations}
        assert bands["a"] == "relaxed"
        assert bands["b"] == "standard"
        assert bands["c"] == "blocked"

    def test_per_store_threading(self):
        captured = []
        def _stats(eng, store_id):
            captured.append(store_id)
            return (5, 0)
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
            return_value=["a"],
        ), patch(
            "engines.confidence_calibrator.calibrator."
            "_engine_outcome_stats",
            side_effect=_stats,
        ):
            calibrate(store_id="storeA", min_sample=5)
        assert captured == ["storeA"]

    def test_band_counts_tallied(self):
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
            return_value=["a", "b", "c"],
        ), patch(
            "engines.confidence_calibrator.calibrator."
            "_engine_outcome_stats",
            side_effect=[(10, 0), (10, 0), (3, 7)],
        ):
            r = calibrate(min_sample=5)
        assert r.band_counts.get("relaxed") == 2
        assert r.band_counts.get("blocked") == 1

    def test_sort_blocked_first(self):
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
            return_value=["good", "bad"],
        ), patch(
            "engines.confidence_calibrator.calibrator."
            "_engine_outcome_stats",
            side_effect=[
                (10, 0),    # good
                (3, 7),     # bad
            ],
        ):
            r = calibrate(min_sample=5)
        # Blocked engines come first
        assert r.calibrations[0].engine == "bad"

    def test_engines_param_overrides_lookup(self):
        with patch(
            "engines.confidence_calibrator.calibrator."
            "_list_engines",
        ) as list_mock, patch(
            "engines.confidence_calibrator.calibrator."
            "_engine_outcome_stats",
            return_value=(0, 0),
        ):
            calibrate(engines=["x", "y"], min_sample=5)
        # When engines passed explicitly, lookup not used
        assert not list_mock.called


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = ConfidenceCalibratorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = ConfidenceCalibratorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = ConfidenceCalibratorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = ConfidenceCalibratorEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = ConfidenceCalibratorEngine().run({})
        assert (
            r["meta"]["engine"] == "confidence_calibrator"
        )


class TestEngineActions:
    def test_min_sample_threaded(self):
        r = ConfidenceCalibratorEngine().run({
            "data": {"min_sample": 10},
        })
        assert r["data"]["min_sample"] == 10

    def test_invalid_min_sample_falls_back(self):
        r = ConfidenceCalibratorEngine().run({
            "data": {"min_sample": "abc"},
        })
        assert r["data"]["min_sample"] == 5

    def test_min_sample_floor(self):
        r = ConfidenceCalibratorEngine().run({
            "data": {"min_sample": 0},
        })
        assert r["data"]["min_sample"] == 1

    def test_band_thresholds_emitted(self):
        r = ConfidenceCalibratorEngine().run({})
        bt = r["data"]["band_thresholds"]
        assert "relaxed" in bt
        assert "blocked" in bt
