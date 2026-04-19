"""Progress estimator tests."""
from __future__ import annotations

import time
import unittest

from core.brain import progress_estimator as pe


def _m(name, weight, done=False, completed_at=None, due_at=None):
    return pe.Milestone(
        name=name, weight=weight, done=done,
        completed_at=completed_at, due_at=due_at,
    )


class TestPercent(unittest.TestCase):
    def test_none_done(self) -> None:
        r = pe.estimate("g", [_m("a", 50), _m("b", 50)])
        self.assertEqual(r.percent_complete, 0.0)

    def test_half_done_by_weight(self) -> None:
        r = pe.estimate("g", [
            _m("a", 40, done=True),
            _m("b", 60),
        ])
        self.assertAlmostEqual(r.percent_complete, 40.0)

    def test_all_done(self) -> None:
        r = pe.estimate("g", [
            _m("a", 50, done=True),
            _m("b", 50, done=True),
        ])
        self.assertEqual(r.percent_complete, 100.0)
        self.assertEqual(r.health, "done")

    def test_zero_total_weight_no_crash(self) -> None:
        r = pe.estimate("g", [_m("a", 0)])
        self.assertEqual(r.percent_complete, 0.0)


class TestPace(unittest.TestCase):
    def test_pace_from_recent_completions(self) -> None:
        now = time.time()
        milestones = [
            _m(f"m{i}", 10, done=True, completed_at=now - i * 86_400)
            for i in range(4)
        ]
        # 4 completed in 4 days
        r = pe.estimate("g", milestones, now=now, pace_window_days=7.0)
        self.assertAlmostEqual(r.pace_per_day, 4 / 7, places=2)

    def test_zero_pace_stalled(self) -> None:
        r = pe.estimate("g", [_m("a", 100)])
        self.assertEqual(r.pace_per_day, 0.0)
        self.assertEqual(r.health, "stalled")


class TestETA(unittest.TestCase):
    def test_eta_infers_remaining(self) -> None:
        now = time.time()
        milestones = [
            _m("a", 25, done=True, completed_at=now - 1 * 86_400),
            _m("b", 25, done=True, completed_at=now - 2 * 86_400),
            _m("c", 25),
            _m("d", 25),
        ]
        # pace = 2 / 7 ≈ 0.286 per day; 2 remaining → ETA ≈ 7 days
        r = pe.estimate("g", milestones, now=now)
        self.assertIsNotNone(r.eta_days)
        self.assertGreater(r.eta_days, 3)

    def test_eta_zero_when_done(self) -> None:
        r = pe.estimate("g", [_m("a", 100, done=True)])
        self.assertEqual(r.eta_days, 0.0)

    def test_eta_none_when_no_pace(self) -> None:
        r = pe.estimate("g", [_m("a", 100)])
        self.assertIsNone(r.eta_days)


class TestHealth(unittest.TestCase):
    def test_blocked_with_pace_at_risk(self) -> None:
        now = time.time()
        milestones = [
            _m("a", 50, done=True, completed_at=now - 1 * 86_400),
            _m("b", 50, due_at=now - 86_400),   # overdue
        ]
        r = pe.estimate("g", milestones, now=now)
        self.assertEqual(r.health, "at_risk")
        self.assertIn("b", r.blocked_milestones)

    def test_blocked_without_pace_stalled(self) -> None:
        now = time.time()
        milestones = [
            _m("a", 100, due_at=now - 86_400),
        ]
        r = pe.estimate("g", milestones, now=now)
        self.assertEqual(r.health, "stalled")

    def test_on_track_with_pace_no_blocks(self) -> None:
        now = time.time()
        milestones = [
            _m("a", 50, done=True, completed_at=now - 1 * 86_400),
            _m("b", 50),
        ]
        r = pe.estimate("g", milestones, now=now)
        self.assertEqual(r.health, "on_track")


class TestEmpty(unittest.TestCase):
    def test_empty_stalled(self) -> None:
        r = pe.estimate("empty", [])
        self.assertEqual(r.health, "stalled")
        self.assertEqual(r.percent_complete, 0.0)


class TestBatch(unittest.TestCase):
    def test_batch_sorts_urgent_first(self) -> None:
        now = time.time()
        goals = {
            "done": [_m("a", 100, done=True)],
            "stalled": [_m("a", 100, due_at=now - 86_400)],
            "on_track": [
                _m("a", 50, done=True,
                    completed_at=now - 1 * 86_400),
                _m("b", 50),
            ],
        }
        reports = pe.estimate_batch(goals, now=now)
        self.assertEqual(reports[0].health, "stalled")
        self.assertEqual(reports[-1].health, "done")


class TestDict(unittest.TestCase):
    def test_dict_milestone_coerced(self) -> None:
        r = pe.estimate("g", [{"name": "a", "weight": 100, "done": True}])
        self.assertEqual(r.percent_complete, 100.0)

    def test_report_as_dict(self) -> None:
        r = pe.estimate("g", [_m("a", 100)])
        d = r.as_dict()
        for key in (
            "goal_id", "percent_complete", "pace_per_day",
            "eta_days", "health", "blocked_milestones",
            "milestones_done", "total_milestones",
        ):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
