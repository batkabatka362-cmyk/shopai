"""Anomaly triage tests."""
from __future__ import annotations

import unittest

from core.brain import anomaly_triage as at


def _ev(**kwargs):
    return at.SurpriseLike(
        signature=kwargs.get("signature", "roas:audio"),
        magnitude=kwargs.get("magnitude", 0.5),
        kind=kwargs.get("kind", "outlier"),
        z_score=kwargs.get("z_score"),
        narrative=kwargs.get("narrative", ""),
    )


class TestLowMagnitude(unittest.TestCase):
    def test_below_threshold_dismissed(self) -> None:
        v = at.triage(_ev(magnitude=0.1))
        self.assertEqual(v.verdict, "dismiss")
        self.assertEqual(v.route, "noop")


class TestEscalate(unittest.TestCase):
    def test_refund_signature_escalates(self) -> None:
        v = at.triage(_ev(signature="refund:audio", magnitude=0.5))
        self.assertEqual(v.verdict, "escalate")
        self.assertEqual(v.route, "ethics_gate")

    def test_negative_z_escalates(self) -> None:
        v = at.triage(_ev(signature="misc", magnitude=0.5, z_score=-3))
        self.assertEqual(v.verdict, "escalate")

    def test_bad_token_in_narrative(self) -> None:
        v = at.triage(_ev(
            signature="event:x", magnitude=0.5,
            narrative="churn spike detected",
        ))
        self.assertEqual(v.verdict, "escalate")

    def test_high_magnitude_escalate_priority(self) -> None:
        v = at.triage(_ev(signature="refund", magnitude=1.0))
        self.assertGreaterEqual(v.priority, 0.9)


class TestCelebrate(unittest.TestCase):
    def test_positive_roas_celebrates(self) -> None:
        v = at.triage(_ev(
            signature="roas:audio", magnitude=0.8, z_score=3,
        ))
        self.assertEqual(v.verdict, "celebrate")
        self.assertEqual(v.route, "opportunity_scout")

    def test_positive_revenue_celebrates(self) -> None:
        v = at.triage(_ev(
            signature="revenue:scale", magnitude=0.85,
        ))
        self.assertEqual(v.verdict, "celebrate")


class TestInvestigateNovel(unittest.TestCase):
    def test_novel_high_magnitude(self) -> None:
        v = at.triage(_ev(
            signature="new_event:x", magnitude=0.9, kind="novel",
        ))
        self.assertEqual(v.verdict, "investigate")
        self.assertEqual(v.route, "debate")


class TestDefaultInvestigate(unittest.TestCase):
    def test_unclear_event_investigates(self) -> None:
        v = at.triage(_ev(
            signature="unknown:signal", magnitude=0.5,
        ))
        self.assertEqual(v.verdict, "investigate")
        self.assertEqual(v.route, "metacognition")


class TestBatch(unittest.TestCase):
    def test_batch_priority_sorted(self) -> None:
        events = [
            _ev(signature="roas:a", magnitude=0.9, z_score=3),
            _ev(signature="refund:b", magnitude=0.5),
            _ev(signature="misc", magnitude=0.1),
        ]
        batch = at.triage_batch(events)
        # Most urgent first
        self.assertGreaterEqual(batch[0].priority, batch[-1].priority)

    def test_stats_counts(self) -> None:
        verdicts = at.triage_batch([
            _ev(signature="refund", magnitude=0.5),
            _ev(signature="roas", magnitude=0.8, z_score=3),
            _ev(signature="x", magnitude=0.1),
            _ev(signature="y", magnitude=0.4),
        ])
        counts = at.stats(verdicts)
        self.assertEqual(counts["escalate"], 1)
        self.assertEqual(counts["celebrate"], 1)
        self.assertEqual(counts["dismiss"], 1)
        self.assertEqual(counts["investigate"], 1)


class TestPriorities(unittest.TestCase):
    def test_priorities_bounded_0_to_1(self) -> None:
        for mag in (0.0, 0.5, 1.0, 5.0):
            v = at.triage(_ev(
                signature="roas", magnitude=mag, z_score=3,
            ))
            self.assertGreaterEqual(v.priority, 0.0)
            self.assertLessEqual(v.priority, 1.0)


if __name__ == "__main__":
    unittest.main()
