"""World-model updater tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import world_model_updater as wmu


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            wmu.WorldModelUpdater(window=3)

    def test_bad_min_samples_raises(self) -> None:
        with self.assertRaises(ValueError):
            wmu.WorldModelUpdater(min_samples=2)

    def test_bad_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            wmu.WorldModelUpdater(drift_threshold=0)


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.u = wmu.WorldModelUpdater()

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.u.record(
                predictor_id="", predicted=1.0, observed=1.0,
            )

    def test_record_stored(self) -> None:
        r = self.u.record(
            predictor_id="cvr_model",
            predicted=0.1, observed=0.09,
        )
        self.assertAlmostEqual(r.error, -0.01, places=5)


class TestMetrics(unittest.TestCase):
    def setUp(self) -> None:
        self.u = wmu.WorldModelUpdater(min_samples=4)

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(self.u.metrics("no_such"))

    def test_zero_error_zero_mse(self) -> None:
        for _ in range(10):
            self.u.record(
                predictor_id="p",
                predicted=1.0, observed=1.0,
            )
        m = self.u.metrics("p")
        self.assertEqual(m.mse, 0.0)
        self.assertEqual(m.bias, 0.0)

    def test_positive_bias(self) -> None:
        # Predicted 1.0, observed 2.0 → bias = +1
        for _ in range(10):
            self.u.record(
                predictor_id="p",
                predicted=1.0, observed=2.0,
            )
        m = self.u.metrics("p")
        self.assertAlmostEqual(m.bias, 1.0, places=4)


class TestDriftDetection(unittest.TestCase):
    def test_no_drift_no_alerts(self) -> None:
        u = wmu.WorldModelUpdater(
            window=60, min_samples=10, drift_threshold=2.0,
        )
        # Consistent small error throughout
        for _ in range(20):
            u.record(
                predictor_id="p",
                predicted=1.0, observed=1.05,
            )
        alerts = u.detect_alerts()
        self.assertEqual(len(alerts), 0)

    def test_growing_error_triggers_alert(self) -> None:
        u = wmu.WorldModelUpdater(
            window=60, min_samples=10, drift_threshold=2.0,
        )
        # First half: predicted≈observed; second half: error grows.
        for i in range(20):
            u.record(
                predictor_id="p",
                predicted=1.0,
                observed=(1.0 if i < 10 else 2.0),
            )
        alerts = u.detect_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].predictor_id, "p")
        self.assertGreater(alerts[0].drift_score, 2.0)

    def test_small_sample_no_alert(self) -> None:
        u = wmu.WorldModelUpdater(
            window=60, min_samples=10, drift_threshold=2.0,
        )
        for _ in range(4):
            u.record(
                predictor_id="p",
                predicted=1.0, observed=5.0,
            )
        self.assertEqual(len(u.detect_alerts()), 0)


class TestAllMetrics(unittest.TestCase):
    def test_ranked_by_drift(self) -> None:
        u = wmu.WorldModelUpdater(
            window=60, min_samples=10, drift_threshold=2.0,
        )
        # Drifty predictor
        for i in range(20):
            u.record(
                predictor_id="p_drift",
                predicted=1.0,
                observed=(1.0 if i < 10 else 3.0),
            )
        # Stable predictor
        for _ in range(20):
            u.record(
                predictor_id="p_stable",
                predicted=1.0, observed=1.01,
            )
        ms = u.all_metrics()
        self.assertEqual(ms[0].predictor_id, "p_drift")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "w.db"
        first = wmu.WorldModelUpdater(path)
        first.record(
            predictor_id="p",
            predicted=1.0, observed=1.5,
        )
        first.close()
        second = wmu.WorldModelUpdater(path)
        s = second.stats()
        self.assertEqual(s["total_records"], 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        u = wmu.WorldModelUpdater()
        u.record(
            predictor_id="p",
            predicted=1.0, observed=1.0,
        )
        s = u.stats()
        self.assertEqual(s["tracked_predictors"], 1)
        self.assertEqual(s["total_records"], 1)
        self.assertIn("drift_threshold", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        u = wmu.WorldModelUpdater()
        u.record(
            predictor_id="p",
            predicted=1.0, observed=1.0,
        )
        self.assertEqual(u.reset(), 1)


class TestDict(unittest.TestCase):
    def test_record_serialises(self) -> None:
        r = wmu.PredictionRecord(
            predictor_id="p",
            predicted=1.0, observed=1.5, ts=100.0,
        )
        d = r.as_dict()
        self.assertEqual(d["error"], 0.5)

    def test_alert_serialises(self) -> None:
        u = wmu.WorldModelUpdater(min_samples=4)
        for i in range(10):
            u.record(
                predictor_id="p",
                predicted=1.0,
                observed=(1.0 if i < 5 else 3.0),
            )
        alerts = u.detect_alerts()
        if alerts:
            d = alerts[0].as_dict()
            self.assertIn("suggestion", d)


if __name__ == "__main__":
    unittest.main()
