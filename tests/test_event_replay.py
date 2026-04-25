"""Event replay tests."""
from __future__ import annotations

import unittest

from core.brain import event_replay as er


def _ev(ts, kind="x", ctx=None, action="realised", reward=1.0):
    return er.Event(
        ts=ts, kind=kind, context=ctx or {},
        realised_action=action, realised_reward=reward,
    )


class TestReplay(unittest.TestCase):
    def test_empty_replay(self) -> None:
        rep = er.replay([], lambda e: None, lambda e, a: 0)
        self.assertEqual(rep.n, 0)
        self.assertEqual(rep.total_realised, 0)
        self.assertEqual(rep.delta, 0)

    def test_better_policy_positive_delta(self) -> None:
        events = [_ev(ts=i, reward=1.0) for i in range(5)]
        rep = er.replay(
            events,
            policy=lambda e: "better",
            scorer=lambda e, a: 2.0 if a == "better" else 1.0,
        )
        self.assertEqual(rep.n, 5)
        self.assertAlmostEqual(rep.total_proposed, 10.0)
        self.assertAlmostEqual(rep.total_realised, 5.0)
        self.assertAlmostEqual(rep.delta, 5.0)

    def test_worse_policy_negative_delta(self) -> None:
        events = [_ev(ts=i, reward=5.0) for i in range(5)]
        rep = er.replay(
            events,
            policy=lambda e: "worse",
            scorer=lambda e, a: 1.0,
        )
        self.assertLess(rep.delta, 0)

    def test_win_rate_counted(self) -> None:
        events = [_ev(ts=i) for i in range(4)]
        rep = er.replay(
            events,
            policy=lambda e: "x",
            scorer=lambda e, a: 2.0 if e.ts > 1 else 0.5,
        )
        # 2 of 4 events win (delta > 0)
        self.assertAlmostEqual(rep.win_rate, 0.5)

    def test_dict_event_accepted(self) -> None:
        events = [{
            "ts": 1, "kind": "order", "context": {"niche": "a"},
            "realised_action": "r", "realised_reward": 1.0,
        }]
        rep = er.replay(
            events,
            policy=lambda e: "p",
            scorer=lambda e, a: 3.0,
        )
        self.assertEqual(rep.n, 1)
        self.assertEqual(rep.rows[0].proposed_reward, 3.0)

    def test_bad_policy_uses_realised(self) -> None:
        events = [_ev(ts=1, reward=2.0)]
        def bad_policy(e):
            raise RuntimeError("nope")
        rep = er.replay(
            events,
            policy=bad_policy,
            scorer=lambda e, a: 5.0 if a == "realised" else 0.0,
        )
        # Failed policy falls back to realised action
        self.assertEqual(rep.rows[0].proposed_action, "realised")

    def test_bad_scorer_zero(self) -> None:
        events = [_ev(ts=1, reward=2.0)]
        def bad_scorer(e, a):
            raise RuntimeError("x")
        rep = er.replay(
            events, policy=lambda e: "x", scorer=bad_scorer,
        )
        self.assertEqual(rep.rows[0].proposed_reward, 0.0)

    def test_events_sorted_by_ts(self) -> None:
        events = [_ev(ts=3), _ev(ts=1), _ev(ts=2)]
        rep = er.replay(
            events,
            policy=lambda e: None,
            scorer=lambda e, a: 0,
        )
        ts_order = [r.event.ts for r in rep.rows]
        self.assertEqual(ts_order, [1, 2, 3])

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            er.replay([], lambda e: None, lambda e, a: 0,
                       mode="nope")


class TestSegmentBreakdown(unittest.TestCase):
    def test_by_segment(self) -> None:
        events = [
            _ev(ts=1, ctx={"niche": "audio"}, reward=1),
            _ev(ts=2, ctx={"niche": "audio"}, reward=2),
            _ev(ts=3, ctx={"niche": "fashion"}, reward=1),
        ]
        rep = er.replay(
            events,
            policy=lambda e: "p",
            scorer=lambda e, a: 3.0,
        )
        buckets = rep.by_segment("niche")
        self.assertEqual(buckets["audio"]["n"], 2)
        self.assertAlmostEqual(buckets["audio"]["delta"], 3.0)


class TestCompare(unittest.TestCase):
    def test_compare_picks_best(self) -> None:
        events = [_ev(ts=i, reward=1.0) for i in range(5)]
        result = er.compare_policies(
            events,
            policies={
                "stay": lambda e: "realised",
                "upgrade": lambda e: "better",
            },
            scorer=lambda e, a: 2.0 if a == "better" else 1.0,
        )
        self.assertEqual(result.as_dict()["best"], "upgrade")

    def test_compare_empty_policies(self) -> None:
        result = er.compare_policies(
            [], policies={}, scorer=lambda e, a: 0,
        )
        self.assertIsNone(result.as_dict()["best"])


if __name__ == "__main__":
    unittest.main()
