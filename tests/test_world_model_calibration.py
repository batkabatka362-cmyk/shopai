"""Tests for core.brain.world_model_calibration — Track 10."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.brain.world_model_calibration import (
    CalibratedPrediction,
    CalibrationRecord,
    WorldModelCalibration,
    _band,
    get_world_model_calibration,
    reset_world_model_calibration_for_tests,
)


def _world(mean=1.0, stdev=0.3, samples=10):
    w = MagicMock()
    pred = MagicMock()
    pred.mean = mean
    pred.stdev = stdev
    pred.samples = samples
    w.predict.return_value = pred
    return w


def _build(tmp, *, world=None, **kw):
    defaults = dict(
        db_path=Path(tmp) / "cal.db",
        world_model=world if world is not None else _world(),
    )
    defaults.update(kw)
    return WorldModelCalibration(**defaults)


class TestConfig(unittest.TestCase):
    def test_bad_widen(self):
        with self.assertRaises(ValueError):
            WorldModelCalibration(widen_factor=0.5)


class TestBand(unittest.TestCase):
    def test_uninformed(self):
        self.assertEqual(_band(0, 1.0), "uninformed")

    def test_tight(self):
        self.assertEqual(_band(10, 0.1), "tight")

    def test_moderate(self):
        self.assertEqual(_band(10, 0.5), "moderate")

    def test_loose(self):
        self.assertEqual(_band(10, 2.0), "loose")


class TestRecord(unittest.TestCase):
    def test_record_creates_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            rec = c.record_outcome(
                "roas", predicted=2.0, actual=1.5,
            )
            self.assertEqual(rec.sample_count, 1)
            self.assertAlmostEqual(
                rec.error_abs_ema, 0.5,
            )
            self.assertAlmostEqual(
                rec.bias_ema, -0.5,
            )
            c.close()

    def test_record_ema_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.record_outcome(
                "roas", predicted=2.0, actual=1.5,
            )
            rec = c.record_outcome(
                "roas", predicted=1.5, actual=2.0,
            )
            self.assertEqual(rec.sample_count, 2)
            # EMA α=0.2 → error moves toward 0.5 then 0.5
            # bias moves from -0.5 toward +0.5
            self.assertGreater(rec.bias_ema, -0.5)

    def test_blank_kpi_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            with self.assertRaises(ValueError):
                c.record_outcome(
                    "", predicted=1, actual=1,
                )
            c.close()


class TestPredict(unittest.TestCase):
    def test_predict_no_calibration_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp,
                world=_world(
                    mean=2.0, stdev=0.5, samples=10,
                ),
                widen_factor=1.2,
            )
            pred = c.predict(
                action="launch", kpi="roas",
            )
            self.assertEqual(pred.mean, 2.0)
            self.assertEqual(pred.stdev, 0.5)
            # calibrated = max(stdev, stdev*1.2 + 0) = 0.6
            self.assertAlmostEqual(
                pred.calibrated_stdev, 0.6,
            )
            self.assertEqual(
                pred.bias_adjusted_mean, 2.0,
            )
            c.close()

    def test_predict_widens_after_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp,
                world=_world(stdev=0.3, mean=1.0),
            )
            # Build up calibration error
            for _ in range(10):
                c.record_outcome(
                    "roas", predicted=1.0, actual=2.0,
                )
            pred = c.predict(
                action="launch", kpi="roas",
            )
            # stdev should widen beyond 0.3 because error
            # EMA climbs toward 1.0
            self.assertGreater(
                pred.calibrated_stdev, 0.5,
            )
            c.close()

    def test_predict_bias_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp,
                world=_world(mean=1.0),
            )
            # Predictions consistently under-estimate
            for _ in range(10):
                c.record_outcome(
                    "roas", predicted=1.0, actual=2.0,
                )
            pred = c.predict(
                action="launch", kpi="roas",
            )
            self.assertGreater(
                pred.bias_adjusted_mean, 1.0,
            )
            c.close()

    def test_predict_without_world_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Pass a world that returns None to simulate the
            # "no prediction" path (bypasses the lazy
            # singleton load)
            empty_world = MagicMock()
            empty_world.predict.return_value = None
            c = _build(tmp, world=empty_world)
            pred = c.predict(action="launch")
            self.assertEqual(pred.mean, 0.0)
            self.assertEqual(pred.samples, 0)
            self.assertEqual(pred.band, "uninformed")
            c.close()

    def test_world_model_exception_degrades(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MagicMock()
            w.predict.side_effect = RuntimeError("no db")
            c = _build(tmp, world=w)
            pred = c.predict(action="x")
            self.assertEqual(pred.samples, 0)
            c.close()

    def test_explanation_populated(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(
                tmp,
                world=_world(
                    mean=1.5, stdev=0.4, samples=20,
                ),
            )
            pred = c.predict(
                action="launch", kpi="roas",
            )
            self.assertIn("action=launch", pred.explanation)
            self.assertIn("kpi=roas", pred.explanation)
            c.close()


class TestQueries(unittest.TestCase):
    def test_all_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.record_outcome(
                "roas", predicted=1, actual=1,
            )
            c.record_outcome(
                "cvr", predicted=0.02, actual=0.03,
            )
            self.assertEqual(
                len(c.all_records()), 2,
            )
            c.close()

    def test_stats_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = _build(tmp)
            c.record_outcome(
                "roas", predicted=1, actual=1,
            )
            s = c.stats()
            self.assertIn("roas", s["tracked_kpis"])
            c.close()


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_world_model_calibration_for_tests()
        try:
            a = get_world_model_calibration()
            b = get_world_model_calibration()
            self.assertIs(a, b)
        finally:
            reset_world_model_calibration_for_tests()


class TestDicts(unittest.TestCase):
    def test_record_dict(self):
        r = CalibrationRecord(
            kpi="roas", sample_count=1,
            error_abs_ema=0.1, bias_ema=0.05,
            last_update_ts=1.0,
        )
        self.assertIn("kpi", r.as_dict())

    def test_prediction_dict(self):
        p = CalibratedPrediction(
            kpi="roas", mean=1.0, stdev=0.2,
            calibrated_stdev=0.3, samples=5,
            bias_adjusted_mean=1.05, band="moderate",
            calibration_sample_count=3,
        )
        self.assertIn("band", p.as_dict())


if __name__ == "__main__":
    unittest.main()
