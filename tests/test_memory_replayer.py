"""Memory replayer tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from core.brain import memory_replayer as mr


@dataclass
class _FakeEvent:
    kind: str
    payload: dict[str, Any]
    cycle_id: str = "c1"


def _make_recent(events):
    def fn(**kwargs):
        kind = kwargs.get("kind")
        if kind:
            return [e for e in events if e.kind == kind]
        return events
    return fn


class TestReplayOutcomes(unittest.TestCase):
    def test_full_agreement(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {
                    "context": {"niche": "audio"},
                    "chosen": {"action": "scale"},
                },
            ),
            _FakeEvent(
                "decision",
                {
                    "context": {"niche": "fashion"},
                    "chosen": {"action": "scale"},
                },
            ),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        rep = r.replay_outcomes(policy=lambda ctx: "scale")
        self.assertEqual(rep.inspected, 2)
        self.assertEqual(rep.agreed, 2)
        self.assertEqual(rep.diverged, 0)
        self.assertEqual(rep.agreement_rate, 1.0)

    def test_full_divergence(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {
                    "context": {"niche": "audio"},
                    "chosen": {"action": "scale"},
                },
            ),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        rep = r.replay_outcomes(policy=lambda ctx: "kill")
        self.assertEqual(rep.diverged, 1)
        self.assertEqual(rep.agreed, 0)
        self.assertEqual(rep.agreement_rate, 0.0)
        self.assertEqual(len(rep.examples), 1)

    def test_policy_returns_none_skips(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {
                    "context": {"x": 1},
                    "chosen": {"action": "scale"},
                },
            ),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        rep = r.replay_outcomes(policy=lambda ctx: None)
        self.assertEqual(rep.inspected, 0)

    def test_policy_raise_handled(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {
                    "context": {"x": 1},
                    "chosen": {"action": "scale"},
                },
            ),
        ]

        def boom(_):
            raise RuntimeError("x")

        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        rep = r.replay_outcomes(policy=boom)
        self.assertEqual(rep.inspected, 0)


class TestMissedPatterns(unittest.TestCase):
    def test_consistent_loser_flagged(self) -> None:
        events: list[Any] = []
        for i in range(6):
            events.append(_FakeEvent(
                "decision",
                {
                    "context": {"niche": "audio", "price": 30},
                    "chosen": {"action": "scale"},
                },
                cycle_id=f"c{i}",
            ))
            events.append(_FakeEvent(
                "outcome",
                {"kpi": "roas", "value": -1.0},
                cycle_id=f"c{i}",
            ))
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        patterns = r.find_missed_patterns(min_support=3)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].sample_decision, "scale")
        self.assertGreaterEqual(patterns[0].wrong_rate, 0.6)

    def test_winners_not_flagged(self) -> None:
        events: list[Any] = []
        for i in range(6):
            events.append(_FakeEvent(
                "decision",
                {
                    "context": {"niche": "audio"},
                    "chosen": {"action": "scale"},
                },
                cycle_id=f"c{i}",
            ))
            events.append(_FakeEvent(
                "outcome",
                {"kpi": "revenue", "value": 5.0},
                cycle_id=f"c{i}",
            ))
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        patterns = r.find_missed_patterns(min_support=3)
        self.assertEqual(patterns, [])

    def test_below_support_not_flagged(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {"context": {"x": 1}, "chosen": {"action": "kill"}},
                cycle_id="c1",
            ),
            _FakeEvent(
                "outcome",
                {"value": -1},
                cycle_id="c1",
            ),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        patterns = r.find_missed_patterns(min_support=5)
        self.assertEqual(patterns, [])

    def test_wrong_threshold_respected(self) -> None:
        events: list[Any] = []
        # 4 wins, 6 losses → wrong_rate 0.6
        for i in range(10):
            events.append(_FakeEvent(
                "decision",
                {
                    "context": {"niche": "audio"},
                    "chosen": {"action": "scale"},
                },
                cycle_id=f"c{i}",
            ))
            events.append(_FakeEvent(
                "outcome",
                {"value": -1 if i < 6 else 1},
                cycle_id=f"c{i}",
            ))
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        # threshold 0.7 → not flagged
        self.assertEqual(
            r.find_missed_patterns(
                min_support=5, wrong_threshold=0.7,
            ),
            [],
        )
        # threshold 0.5 → flagged
        self.assertEqual(
            len(r.find_missed_patterns(
                min_support=5, wrong_threshold=0.5,
            )),
            1,
        )


class TestSample(unittest.TestCase):
    def test_sample_filters_by_kind(self) -> None:
        events = [
            _FakeEvent("decision", {}),
            _FakeEvent("outcome", {}),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        d = r.sample(kind="decision")
        self.assertEqual(len(d), 1)


class TestStats(unittest.TestCase):
    def test_stats_when_recorder_present(self) -> None:
        events = [_FakeEvent("decision", {})]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        s = r.stats()
        self.assertTrue(s["decisions_visible"])

    def test_stats_when_recorder_empty(self) -> None:
        r = mr.MemoryReplayer(recent_fn=_make_recent([]))
        s = r.stats()
        self.assertFalse(s["decisions_visible"])


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        events = [
            _FakeEvent(
                "decision",
                {"context": {"x": 1}, "chosen": {"action": "y"}},
            ),
        ]
        r = mr.MemoryReplayer(recent_fn=_make_recent(events))
        d = r.replay_outcomes(policy=lambda c: "y").as_dict()
        self.assertIn("agreement_rate", d)

    def test_pattern_serialises(self) -> None:
        p = mr.MissedPattern(
            signature="x=1", n_total=10, n_wrong=8,
            sample_decision="kill", sample_outcome_value=-1.0,
        )
        d = p.as_dict()
        self.assertIn("wrong_rate", d)


class TestSignature(unittest.TestCase):
    def test_drop_keys_excluded(self) -> None:
        sig1 = mr._signature(
            {"x": 1, "ts": 1000, "cycle_id": "c1"},
            drop=("ts", "cycle_id"),
        )
        sig2 = mr._signature(
            {"x": 1, "ts": 9999, "cycle_id": "c2"},
            drop=("ts", "cycle_id"),
        )
        self.assertEqual(sig1, sig2)


if __name__ == "__main__":
    unittest.main()
