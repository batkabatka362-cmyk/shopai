"""Temporal reasoning — weekday/hour/seasonality math."""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from core.brain import temporal as tm


def _monday_ts(hour: int = 12) -> float:
    # 2025-01-06 was a Monday (UTC)
    return datetime(2025, 1, 6, hour, 0, tzinfo=timezone.utc).timestamp()


class TestDayOfWeek(unittest.TestCase):
    def test_mean_per_day_and_best_worst(self) -> None:
        rows = [
            (_monday_ts(), 5.0),    # Mon
            (_monday_ts() + 86_400, 1.0),  # Tue
            (_monday_ts() + 2 * 86_400, 4.0),  # Wed
            (_monday_ts() + 6 * 86_400, 3.0),  # Sun
        ]
        with patch.object(tm, "_pull_events", return_value=rows):
            prof = tm.day_of_week("order")
        self.assertEqual(prof.best_day, 0)         # Monday highest
        self.assertEqual(prof.worst_day, 1)        # Tuesday lowest
        self.assertAlmostEqual(prof.per_day[0], 5.0)
        self.assertEqual(prof.sample_counts[0], 1)

    def test_empty_returns_zeros(self) -> None:
        with patch.object(tm, "_pull_events", return_value=[]):
            prof = tm.day_of_week("order")
        self.assertEqual(prof.per_day, {i: 0.0 for i in range(7)})


class TestHourOfDay(unittest.TestCase):
    def test_peak_hour_computed(self) -> None:
        rows = [
            (_monday_ts(hour=9), 2.0),
            (_monday_ts(hour=14), 5.0),
            (_monday_ts(hour=14) + 86_400, 5.0),
            (_monday_ts(hour=22), 3.0),
        ]
        with patch.object(tm, "_pull_events", return_value=rows):
            prof = tm.hour_of_day("order")
        self.assertEqual(prof.peak_hour, 14)


class TestConvergenceDays(unittest.TestCase):
    def test_empty_niche_returns_zero(self) -> None:
        stats = tm.convergence_days("")
        self.assertEqual(stats.samples, 0)
        self.assertEqual(stats.median_days, 0)

    def test_percentile_computation(self) -> None:
        fake_deltas = [1.0, 2.0, 3.0, 4.0, 5.0]
        with patch.object(tm, "_launch_to_verdict_deltas",
                          return_value=fake_deltas):
            stats = tm.convergence_days("audio")
        self.assertEqual(stats.samples, 5)
        self.assertAlmostEqual(stats.median_days, 3.0)


class TestAutocorr(unittest.TestCase):
    def test_perfect_periodicity(self) -> None:
        series = [1, 0, 0, 0, 0, 0, 0] * 4   # weekly spike
        self.assertGreater(tm._autocorr(series, lag=7), 0.5)

    def test_noise_close_to_zero(self) -> None:
        series = [5, 3, 8, 2, 6, 1, 9, 4, 7, 0]
        result = tm._autocorr(series, lag=7)
        self.assertLess(abs(result), 0.6)

    def test_too_short_returns_zero(self) -> None:
        self.assertEqual(tm._autocorr([1, 2, 3], lag=7), 0.0)


class TestDispatcher(unittest.TestCase):
    def test_weekday_keyword_routes(self) -> None:
        with patch.object(tm, "day_of_week") as mock:
            mock.return_value.as_dict.return_value = {"ok": True}
            out = tm.answer("what's the best weekday?")
        self.assertEqual(out, {"ok": True})

    def test_peak_hour_keyword_routes(self) -> None:
        with patch.object(tm, "hour_of_day") as mock:
            mock.return_value.as_dict.return_value = {"hour": 14}
            out = tm.answer("what's our peak hour?")
        self.assertEqual(out, {"hour": 14})

    def test_unknown_returns_error(self) -> None:
        out = tm.answer("unrelated question")
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
