"""Anticipation engine tests."""
from __future__ import annotations

import time
import unittest

from core.brain import anticipation as an


class TestLinearFit(unittest.TestCase):
    def test_perfect_line(self) -> None:
        xs = [0, 1, 2, 3, 4]
        ys = [1, 3, 5, 7, 9]       # y = 2x + 1
        slope, intercept = an.linear_fit(xs, ys)
        self.assertAlmostEqual(slope, 2.0)
        self.assertAlmostEqual(intercept, 1.0)

    def test_single_point_returns_zero_slope(self) -> None:
        slope, _ = an.linear_fit([1], [5])
        self.assertEqual(slope, 0.0)


class TestExtrapolate(unittest.TestCase):
    def test_below_threshold_crossing_detected(self) -> None:
        # ROAS declining from 3.0 toward 1.0 in steps of 0.3
        xs = [0, 1, 2, 3, 4]
        ys = [3.0, 2.7, 2.4, 2.1, 1.8]
        p = an.extrapolate(
            subject="roas:audio", xs=xs, ys=ys,
            threshold=1.5, direction="below",
            horizon_steps=10, suggested_action="propose_kill",
        )
        self.assertIsNotNone(p)
        self.assertEqual(p.kind, "threshold_cross")
        self.assertIn("cross", p.text)

    def test_rising_series_wont_trigger_below(self) -> None:
        xs = [0, 1, 2, 3]
        ys = [1.0, 1.2, 1.4, 1.6]
        p = an.extrapolate(
            subject="x", xs=xs, ys=ys,
            threshold=0.5, direction="below",
        )
        self.assertIsNone(p)

    def test_flat_series_returns_none(self) -> None:
        xs = [0, 1, 2]
        ys = [2.0, 2.0, 2.0]
        p = an.extrapolate(
            subject="x", xs=xs, ys=ys,
            threshold=1.0, direction="below",
        )
        self.assertIsNone(p)

    def test_too_far_in_future_returns_none(self) -> None:
        # Trending down very slowly; threshold far away
        xs = [0, 1, 2, 3]
        ys = [10.0, 9.99, 9.98, 9.97]
        p = an.extrapolate(
            subject="x", xs=xs, ys=ys,
            threshold=0.0, direction="below",
            horizon_steps=5,
        )
        self.assertIsNone(p)

    def test_insufficient_data_returns_none(self) -> None:
        p = an.extrapolate(
            subject="x", xs=[0, 1], ys=[1.0, 0.5],
            threshold=0.0, direction="below",
        )
        self.assertIsNone(p)


class TestEventRate(unittest.TestCase):
    def test_frequent_events_predict_next(self) -> None:
        now = time.time()
        # One event per day for 20 days
        ts = [now - i * 86_400 for i in range(20)]
        p = an.event_rate_probability(
            subject="support_ticket",
            event_timestamps=ts,
            horizon_s=86_400, now=now,
        )
        self.assertIsNotNone(p)
        # 20 events in 30d → rate ~0.67/day → P(≥1) ≈ 0.49
        self.assertGreater(p.confidence, 0.4)

    def test_rare_events_no_prediction(self) -> None:
        now = time.time()
        ts = [now - 20 * 86_400, now - 10 * 86_400]   # 2 in 30 days
        p = an.event_rate_probability(
            subject="rare_event", event_timestamps=ts,
            horizon_s=3_600, now=now,     # 1 hour horizon
        )
        self.assertIsNone(p)

    def test_empty_timestamps_returns_none(self) -> None:
        p = an.event_rate_probability(
            subject="x", event_timestamps=[],
        )
        self.assertIsNone(p)

    def test_single_event_returns_none(self) -> None:
        p = an.event_rate_probability(
            subject="x", event_timestamps=[time.time()],
        )
        self.assertIsNone(p)


class TestCompose(unittest.TestCase):
    def test_compose_filters_none_and_low_conf(self) -> None:
        xs = [0, 1, 2, 3]
        ys = [2.0, 1.7, 1.4, 1.1]
        p1 = an.extrapolate(
            subject="a", xs=xs, ys=ys,
            threshold=0.5, direction="below",
        )
        # Manually stuff a low-confidence prediction.
        p2 = an.Prediction(
            subject="b", kind="x", text="x", confidence=0.1,
        )
        out = an.compose([p1, p2, None], min_confidence=0.3)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].subject, "a")

    def test_compose_orders_by_confidence(self) -> None:
        p1 = an.Prediction("a", "x", "x", 0.5)
        p2 = an.Prediction("b", "x", "x", 0.9)
        p3 = an.Prediction("c", "x", "x", 0.7)
        out = an.compose([p1, p2, p3])
        self.assertEqual([p.subject for p in out], ["b", "c", "a"])

    def test_compose_top_k_truncates(self) -> None:
        preds = [an.Prediction(f"s{i}", "x", "x",
                                0.5 + 0.05 * i) for i in range(5)]
        out = an.compose(preds, top_k=2)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
