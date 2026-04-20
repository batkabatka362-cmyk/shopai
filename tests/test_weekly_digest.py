"""Weekly digest tests."""
from __future__ import annotations

import calendar
import time
import unittest
from dataclasses import dataclass
from typing import Any

from core.brain import weekly_digest as wd


@dataclass
class _FakeEvent:
    kind: str
    payload: dict[str, Any]
    ts: float


def _now() -> float:
    return time.time()


def _noon_utc_today() -> float:
    """Stable mid-UTC-day anchor so offsets ≤ 11h stay on the same
    UTC day regardless of wall-clock. Pre-audit _hours_ago used
    time.time(); when CI ran near 00:XX UTC, an event 5h ago landed
    on the previous UTC day while an event 1h ago stayed on today,
    so TestRollup.test_per_day_buckets flaked (2 buckets != 1).
    _day_key() in weekly_digest.py formats in UTC via gmtime, so we
    anchor to UTC noon here explicitly."""
    now = time.gmtime()
    return float(calendar.timegm((
        now.tm_year, now.tm_mon, now.tm_mday,
        12, 0, 0, 0, 0, 0,
    )))


def _hours_ago(h: float) -> float:
    return _noon_utc_today() - h * 3600.0


class TestEmpty(unittest.TestCase):
    def test_no_events_returns_empty_digest(self) -> None:
        d = wd.compose([])
        self.assertEqual(d.by_day, [])
        self.assertEqual(d.top_decisions, [])
        self.assertIn("0 decisions", d.headline)

    def test_invalid_period_raises(self) -> None:
        with self.assertRaises(ValueError):
            wd.compose([], period_days=0)


class TestPeriodFilter(unittest.TestCase):
    def test_old_events_filtered_out(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {"action": "x"}},
                        ts=_now() - 60 * 86_400),
            _FakeEvent("decision", {"chosen": {"action": "y"}},
                        ts=_now()),
        ]
        d = wd.compose(events, period_days=7)
        self.assertEqual(len(d.top_decisions), 1)
        self.assertEqual(d.top_decisions[0]["action"], "y")


class TestRollup(unittest.TestCase):
    def test_per_day_buckets(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {}}, ts=_hours_ago(2)),
            _FakeEvent("decision", {"chosen": {}}, ts=_hours_ago(3)),
            _FakeEvent("outcome", {"kpi": "r", "value": 5},
                        ts=_hours_ago(1)),
            _FakeEvent("phase",
                        {"name": "fetch", "status": "failed"},
                        ts=_hours_ago(4)),
            _FakeEvent("llm_call", {"cost_usd": 0.01},
                        ts=_hours_ago(5)),
        ]
        d = wd.compose(events)
        self.assertEqual(len(d.by_day), 1)
        day = d.by_day[0]
        self.assertEqual(day.decisions, 2)
        self.assertEqual(day.outcomes, 1)
        self.assertEqual(day.phase_errors, 1)
        self.assertAlmostEqual(day.llm_cost_usd, 0.01)


class TestTopDecisions(unittest.TestCase):
    def test_sorted_by_confidence(self) -> None:
        events = [
            _FakeEvent("decision",
                        {"chosen": {"action": "a", "confidence": 0.4}},
                        ts=_now()),
            _FakeEvent("decision",
                        {"chosen": {"action": "b", "confidence": 0.9}},
                        ts=_now()),
            _FakeEvent("decision",
                        {"chosen": {"action": "c", "confidence": 0.7}},
                        ts=_now()),
        ]
        d = wd.compose(events)
        self.assertEqual(d.top_decisions[0]["action"], "b")
        self.assertEqual(d.top_decisions[1]["action"], "c")

    def test_caps_at_five(self) -> None:
        events = [
            _FakeEvent("decision",
                        {"chosen": {"action": f"a{i}",
                                    "confidence": 0.5}},
                        ts=_now())
            for i in range(20)
        ]
        d = wd.compose(events)
        self.assertEqual(len(d.top_decisions), 5)


class TestTopMovers(unittest.TestCase):
    def test_largest_swing_first(self) -> None:
        events = [
            _FakeEvent("outcome", {"kpi": "stable", "value": 1.0},
                        ts=_hours_ago(2)),
            _FakeEvent("outcome", {"kpi": "stable", "value": 1.0},
                        ts=_now()),
            _FakeEvent("outcome", {"kpi": "huge", "value": 1.0},
                        ts=_hours_ago(2)),
            _FakeEvent("outcome", {"kpi": "huge", "value": 100.0},
                        ts=_now()),
        ]
        d = wd.compose(events)
        self.assertEqual(d.top_movers[0]["kpi"], "huge")

    def test_single_observation_skipped(self) -> None:
        events = [
            _FakeEvent("outcome", {"kpi": "lonely", "value": 1.0},
                        ts=_now()),
        ]
        d = wd.compose(events)
        self.assertEqual(d.top_movers, [])


class TestRepeatedFailures(unittest.TestCase):
    def test_threshold_triggers(self) -> None:
        events = [
            _FakeEvent(
                "phase",
                {"name": "fetch", "status": "failed"},
                ts=_hours_ago(i),
            )
            for i in range(5)
        ]
        d = wd.compose(events, failure_threshold=3)
        self.assertEqual(d.repeated_failures[0]["phase"], "fetch")
        self.assertEqual(d.repeated_failures[0]["count"], 5)

    def test_below_threshold_skipped(self) -> None:
        events = [
            _FakeEvent("phase",
                        {"name": "x", "status": "failed"}, ts=_now()),
        ]
        d = wd.compose(events, failure_threshold=3)
        self.assertEqual(d.repeated_failures, [])


class TestLlmCost(unittest.TestCase):
    def test_total_cost_summed(self) -> None:
        events = [
            _FakeEvent("llm_call", {"cost_usd": 0.05}, ts=_now()),
            _FakeEvent("llm_call", {"cost_usd": 0.10}, ts=_now()),
            _FakeEvent("llm_call", {"cost_usd": 0.20}, ts=_now()),
        ]
        d = wd.compose(events)
        self.assertAlmostEqual(d.llm_total_cost_usd, 0.35)


class TestDistilled(unittest.TestCase):
    def test_distilled_skills_in_body(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {"action": "x"}},
                        ts=_now()),
        ]
        d = wd.compose(
            events,
            distilled_skills=[
                {"name": "distilled.scale.audio",
                 "support": 12, "mean_score": 4.1},
            ],
        )
        self.assertIn("distilled.scale.audio", d.body)


class TestGenerateDigestInjection(unittest.TestCase):
    def test_injected_recent_fn_used(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {"action": "y"}},
                        ts=_now()),
        ]
        d = wd.generate_digest(recent_fn=lambda **k: events)
        self.assertEqual(d.top_decisions[0]["action"], "y")

    def test_recent_failure_handled(self) -> None:
        def boom(**k):
            raise RuntimeError("db missing")

        d = wd.generate_digest(recent_fn=boom)
        # Should produce an empty digest, not raise
        self.assertEqual(d.by_day, [])


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        events = [
            _FakeEvent("decision", {"chosen": {"action": "x"}},
                        ts=_now()),
        ]
        d = wd.compose(events).as_dict()
        self.assertIn("by_day", d)
        self.assertIn("top_decisions", d)
        self.assertIn("body", d)


if __name__ == "__main__":
    unittest.main()
