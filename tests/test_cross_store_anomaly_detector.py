"""Tests for engines.cross_store_anomaly_detector — W963-33."""
from __future__ import annotations

from engines.cross_store_anomaly_detector import (
    CrossStoreAnomalyDetectorEngine,
)
from engines.cross_store_anomaly_detector.detector import (
    StoreMetrics,
    _mad,
    _median,
    available_metrics,
    detect_anomalies,
)


# ── statistics ────────────────────────────────────────────


class TestMedian:
    def test_empty(self):
        assert _median([]) == 0.0

    def test_odd_count(self):
        assert _median([1, 5, 3]) == 3

    def test_even_count(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_unsorted_input(self):
        assert _median([5, 1, 3, 2, 4]) == 3


class TestMad:
    def test_empty(self):
        assert _mad([]) == (0.0, 0.0)

    def test_uniform(self):
        med, mad = _mad([5, 5, 5, 5])
        assert med == 5
        assert mad == 0.0

    def test_variation(self):
        med, mad = _mad([1, 2, 3, 4, 5])
        assert med == 3
        # Absolute deviations: 2, 1, 0, 1, 2 → median 1
        assert mad == 1.0


# ── detect_anomalies ──────────────────────────────────────


def _make_metrics(values: list[float]) -> list[StoreMetrics]:
    return [
        StoreMetrics(
            store_id=f"s{i}", revenue_7d=v,
        )
        for i, v in enumerate(values, 1)
    ]


class TestDetect:
    def test_small_fleet_skips(self):
        m = _make_metrics([100.0, 200.0])
        r = detect_anomalies(metrics=m)
        assert r.total_stores == 2
        # Too few stores → all metrics skipped
        assert len(r.skipped_metrics) >= 1
        assert r.alerts == []

    def test_uniform_fleet_no_alerts(self):
        m = _make_metrics([100.0, 100.0, 100.0, 100.0])
        r = detect_anomalies(metrics=m)
        # mad = 0 → no alerts emitted
        assert r.alerts == []

    def test_outlier_high_flagged(self):
        # 4 stores at 100, one at 1000 → outlier
        m = _make_metrics([100, 100, 100, 100, 1000])
        r = detect_anomalies(
            metrics=m, mad_threshold=3.0,
        )
        rev_alerts = [
            a for a in r.alerts
            if a.metric == "revenue_7d"
        ]
        assert len(rev_alerts) >= 1
        top = rev_alerts[0]
        assert top.store_id == "s5"
        assert top.direction == "high"

    def test_outlier_low_flagged(self):
        m = _make_metrics([100, 100, 100, 100, 1])
        r = detect_anomalies(
            metrics=m, mad_threshold=3.0,
        )
        rev_alerts = [
            a for a in r.alerts
            if a.metric == "revenue_7d"
        ]
        assert any(a.direction == "low" for a in rev_alerts)

    def test_metric_filter_narrows(self):
        m = _make_metrics([100, 100, 100, 100, 1000])
        r = detect_anomalies(
            metrics=m, metric_filter="revenue_7d",
        )
        assert "revenue_7d" in r.fleet_norms
        assert "funnel_drop_rate" not in r.fleet_norms

    def test_unknown_metric_filter_skipped(self):
        m = _make_metrics([100, 100, 100])
        r = detect_anomalies(
            metrics=m, metric_filter="xyz_unknown",
        )
        assert "xyz_unknown" in r.skipped_metrics

    def test_alerts_sorted_by_deviation_desc(self):
        # Set up 2 outliers with different deviations
        m = [
            StoreMetrics(store_id="s1", revenue_7d=100),
            StoreMetrics(store_id="s2", revenue_7d=100),
            StoreMetrics(store_id="s3", revenue_7d=100),
            StoreMetrics(store_id="s4", revenue_7d=100),
            StoreMetrics(store_id="s5", revenue_7d=500),
            StoreMetrics(store_id="s6", revenue_7d=2000),
        ]
        r = detect_anomalies(
            metrics=m, mad_threshold=2.0,
        )
        if len(r.alerts) >= 2:
            for i in range(len(r.alerts) - 1):
                assert (
                    r.alerts[i].deviation_mads
                    >= r.alerts[i + 1].deviation_mads
                )

    def test_mad_threshold_floor(self):
        m = _make_metrics([100, 100, 100, 100, 1000])
        # Threshold below 0.5 floored to 0.5
        r = detect_anomalies(
            metrics=m, mad_threshold=0.1,
        )
        assert r.mad_threshold == 0.5


# ── available_metrics ─────────────────────────────────────


class TestAvailableMetrics:
    def test_known_keys_present(self):
        keys = available_metrics()
        assert "revenue_7d" in keys
        assert "funnel_drop_rate" in keys
        assert "approval_pending" in keys


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = CrossStoreAnomalyDetectorEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = CrossStoreAnomalyDetectorEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = CrossStoreAnomalyDetectorEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = CrossStoreAnomalyDetectorEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = CrossStoreAnomalyDetectorEngine().run({})
        assert (
            r["meta"]["engine"]
            == "cross_store_anomaly_detector"
        )


class TestEngineActions:
    def test_metrics_threaded(self):
        metrics = _make_metrics(
            [100, 100, 100, 100, 1000],
        )
        r = CrossStoreAnomalyDetectorEngine().run({
            "data": {"metrics": metrics},
        })
        assert r["data"]["total_stores"] == 5
        assert r["data"]["alert_count"] >= 1

    def test_invalid_mad_threshold_falls_back(self):
        r = CrossStoreAnomalyDetectorEngine().run({
            "data": {"mad_threshold": "abc"},
        })
        assert r["status"] == "success"
        assert r["data"]["mad_threshold"] == 3.0

    def test_available_metrics_included(self):
        r = CrossStoreAnomalyDetectorEngine().run({})
        assert "revenue_7d" in r["data"]["available_metrics"]
