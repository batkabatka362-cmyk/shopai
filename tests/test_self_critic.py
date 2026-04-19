"""Self-critic — threshold-tuning math tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.autonomous import self_critic as sc


class TestMoved(unittest.TestCase):
    def test_moves_toward_target_partial(self) -> None:
        # learning rate 0.4 → 40% of delta
        self.assertAlmostEqual(sc._moved(1.5, 2.5), 1.5 + 0.4)

    def test_clamped_max_step(self) -> None:
        # delta 3 * 0.4 = 1.2 but capped at 0.5
        self.assertAlmostEqual(sc._moved(1.0, 4.0), 1.5)

    def test_clamped_min(self) -> None:
        # floor 0.3
        self.assertEqual(sc._moved(0.3, 0.0), 0.3)

    def test_clamped_max(self) -> None:
        self.assertLessEqual(sc._moved(5.9, 10.0), 6.0)


class TestThresholdsRoundtrip(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = sc._THRESHOLDS_PATH
        sc._THRESHOLDS_PATH = Path(self._tmp.name) / "thresh.json"

    def tearDown(self) -> None:
        sc._THRESHOLDS_PATH = self._orig
        self._tmp.cleanup()

    def test_empty_when_absent(self) -> None:
        self.assertEqual(sc._load_thresholds(), {})

    def test_save_load_roundtrip(self) -> None:
        sample = {
            "audio": {"kill_roas": 1.2, "scale_roas": 2.0, "kill_after_days": 3},
        }
        sc._save_thresholds(sample)
        self.assertEqual(sc._load_thresholds(), sample)


class TestCritiquePipeline(unittest.TestCase):
    """Integration-style: seeds a fake evaluator + niche map and asserts
    the public contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        sc._THRESHOLDS_PATH = Path(self._tmp.name) / "thresh.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_updates_only_niches_with_enough_evidence(self) -> None:
        from unittest.mock import patch
        fake_launches = [
            {"launch_id": f"l{i}", "niche": "audio", "verdict": "kill",
             "estimated_roas": 1.1, "revenue_usd": 40, "days_live": 3,
             "order_count": 2}
            for i in range(6)
        ] + [
            {"launch_id": "l_rare_1", "niche": "rare", "verdict": "kill",
             "estimated_roas": 1.0, "revenue_usd": 20, "days_live": 3,
             "order_count": 1}
        ]
        with patch.object(sc, "_load_recent_launches", return_value=fake_launches), \
             patch.object(sc, "_record_memory"):
            report = sc.critique()
        # Only 'audio' has ≥ 5 launches
        self.assertEqual(report.updated_niches, 1)
        self.assertEqual(report.verdicts[0].niche, "audio")
        self.assertEqual(report.verdicts[0].sample_size, 6)

    def test_no_op_when_no_launches(self) -> None:
        from unittest.mock import patch
        with patch.object(sc, "_load_recent_launches", return_value=[]):
            report = sc.critique()
        self.assertEqual(report.updated_niches, 0)
        self.assertEqual(report.launches_considered, 0)


if __name__ == "__main__":
    unittest.main()
