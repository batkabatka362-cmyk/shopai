"""Meta reasoner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import meta_reasoner as mr


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.m = mr.MetaReasoner()

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record(
                decision_id="", claimed_confidence=0.5,
                outcome_positive=True,
            )

    def test_bad_confidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record(
                decision_id="d1", claimed_confidence=1.5,
                outcome_positive=True,
            )

    def test_record_appends(self) -> None:
        self.m.record(
            decision_id="d1", claimed_confidence=0.5,
            outcome_positive=True,
        )
        s = self.m.stats()
        self.assertEqual(s["n_records"], 1)


class TestCalibrate(unittest.TestCase):
    def setUp(self) -> None:
        self.m = mr.MetaReasoner()

    def test_empty_is_zero(self) -> None:
        r = self.m.calibrate()
        self.assertEqual(r.n_total, 0)
        self.assertEqual(r.calibration_error, 0.0)

    def test_well_calibrated(self) -> None:
        # Claim 0.8 → actually succeed 80% of the time
        for i in range(10):
            self.m.record(
                decision_id=f"d{i}",
                claimed_confidence=0.8,
                outcome_positive=(i < 8),
            )
        r = self.m.calibrate()
        # bucket (0.8, 0.9) has mid=0.85 and hit=0.8 → err 0.05
        self.assertLess(r.calibration_error, 0.1)

    def test_overconfident(self) -> None:
        # Claim 0.9 but succeed only 30% of the time
        for i in range(10):
            self.m.record(
                decision_id=f"d{i}",
                claimed_confidence=0.9,
                outcome_positive=(i < 3),
            )
        r = self.m.calibrate()
        self.assertGreater(r.overconfidence_score, 0.5)
        self.assertGreater(r.calibration_error, 0.5)

    def test_underconfident(self) -> None:
        for i in range(10):
            self.m.record(
                decision_id=f"d{i}",
                claimed_confidence=0.2,
                outcome_positive=(i < 9),
            )
        r = self.m.calibrate()
        self.assertLess(r.overconfidence_score, -0.5)


class TestAdjustedConfidence(unittest.TestCase):
    def test_learned_mapping(self) -> None:
        m = mr.MetaReasoner()
        # 0.9 band actually wins only 50%
        for i in range(10):
            m.record(
                decision_id=f"d{i}",
                claimed_confidence=0.9,
                outcome_positive=(i < 5),
            )
        adj = m.adjusted_confidence(0.9)
        self.assertEqual(adj, 0.5)

    def test_bad_input_raises(self) -> None:
        m = mr.MetaReasoner()
        with self.assertRaises(ValueError):
            m.adjusted_confidence(1.5)

    def test_no_data_passthrough(self) -> None:
        m = mr.MetaReasoner()
        adj = m.adjusted_confidence(0.7)
        self.assertEqual(adj, 0.7)


class TestSignalUse(unittest.TestCase):
    def setUp(self) -> None:
        self.m = mr.MetaReasoner()

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record_signal_use(
                decision_id="", signals=["x"],
                outcome_positive=True,
            )

    def test_signal_weights(self) -> None:
        # "roas" present when positive 9/10, negative 1/10
        # "ctr" present when positive 2/10
        for i in range(10):
            pos = i < 9
            self.m.record_signal_use(
                decision_id=f"d{i}",
                signals=["roas", "ctr"] if pos else ["ctr"],
                outcome_positive=pos,
            )
        weights = self.m.signal_weights()
        self.assertGreater(weights["roas"], weights["ctr"])

    def test_low_value_signals(self) -> None:
        for i in range(10):
            self.m.record_signal_use(
                decision_id=f"d{i}",
                signals=["noise"], outcome_positive=(i < 2),
            )
        low = self.m.low_value_signals(floor=0.5)
        self.assertIn("noise", low)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "m.db"
        first = mr.MetaReasoner(path)
        first.record(
            decision_id="d1", claimed_confidence=0.8,
            outcome_positive=True,
        )
        first.record_signal_use(
            decision_id="d1", signals=["cpm"],
            outcome_positive=True,
        )
        first.close()
        second = mr.MetaReasoner(path)
        s = second.stats()
        self.assertEqual(s["n_records"], 1)
        self.assertEqual(s["n_signal_uses"], 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = mr.MetaReasoner()
        s = m.stats()
        self.assertIn("n_records", s)
        self.assertIn("distinct_signals", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        m = mr.MetaReasoner()
        m.record(
            decision_id="d1", claimed_confidence=0.5,
            outcome_positive=True,
        )
        m.record_signal_use(
            decision_id="d1", signals=["x"],
            outcome_positive=True,
        )
        self.assertEqual(m.reset(), 2)


class TestDict(unittest.TestCase):
    def test_bucket_serialises(self) -> None:
        b = mr.BucketStat(low=0.5, high=0.6, n=10, positives=5)
        d = b.as_dict()
        self.assertEqual(d["hit_rate"], 0.5)

    def test_report_serialises(self) -> None:
        m = mr.MetaReasoner()
        m.record(
            decision_id="d1", claimed_confidence=0.5,
            outcome_positive=True,
        )
        r = m.calibrate()
        d = r.as_dict()
        self.assertIn("calibration_error", d)


if __name__ == "__main__":
    unittest.main()
