"""Funnel analyzer tests."""
from __future__ import annotations

import unittest

from core.brain import funnel_analyzer as fa


def _sess(kinds, meta=None):
    """Build a fake session-like dict with events."""
    events = [{"kind": k, "meta": meta or {}} for k in kinds]
    return {"events": events}


class TestAnalyse(unittest.TestCase):
    def test_simple_full_funnel(self) -> None:
        steps = ["visit", "view", "add_to_cart", "checkout", "purchase"]
        sessions = [
            _sess(steps),
            _sess(steps[:4]),
            _sess(steps[:3]),
            _sess(steps[:2]),
            _sess(steps[:1]),
        ]
        report = fa.analyse(sessions, steps)
        # Counts cascade: 5, 4, 3, 2, 1
        counts = [s.count for s in report.steps]
        self.assertEqual(counts, [5, 4, 3, 2, 1])
        self.assertAlmostEqual(
            report.end_to_end_conversion, 1 / 5,
        )

    def test_bottleneck_is_biggest_drop(self) -> None:
        steps = ["a", "b", "c"]
        # 10 reach a, 9 reach b, 2 reach c → biggest drop b→c
        sessions = (
            [_sess(steps) for _ in range(2)]
            + [_sess(steps[:2]) for _ in range(7)]
            + [_sess(steps[:1]) for _ in range(1)]
        )
        report = fa.analyse(sessions, steps)
        self.assertEqual(report.bottleneck_step, "c")

    def test_empty_sessions(self) -> None:
        report = fa.analyse([], ["a", "b"])
        self.assertEqual(report.total_sessions, 0)
        self.assertEqual(report.steps[0].count, 0)

    def test_empty_steps(self) -> None:
        report = fa.analyse([_sess(["x"])], [])
        self.assertEqual(report.steps, [])

    def test_invariant_step_counts_monotone_decreasing(self) -> None:
        steps = ["a", "b", "c"]
        sessions = [_sess(["c", "b", "a"]) for _ in range(5)]
        report = fa.analyse(sessions, steps)
        counts = [s.count for s in report.steps]
        for i in range(1, len(counts)):
            self.assertLessEqual(counts[i], counts[i - 1])

    def test_skip_middle_step_breaks_funnel(self) -> None:
        # Session has a + c but not b → should count only a
        sessions = [_sess(["a", "c"])]
        report = fa.analyse(sessions, ["a", "b", "c"])
        self.assertEqual(report.steps[0].count, 1)
        self.assertEqual(report.steps[1].count, 0)
        self.assertEqual(report.steps[2].count, 0)


class TestSegmented(unittest.TestCase):
    def test_segmented_by_niche(self) -> None:
        steps = ["visit", "purchase"]
        sessions = [
            _sess(["visit", "purchase"], meta={"niche": "audio"}),
            _sess(["visit"], meta={"niche": "audio"}),
            _sess(["visit", "purchase"], meta={"niche": "fashion"}),
            _sess(["visit", "purchase"], meta={"niche": "fashion"}),
        ]
        reports = fa.analyse_segmented(
            sessions, steps, segment_key="niche",
        )
        self.assertEqual(reports["audio"].steps[-1].count, 1)
        self.assertEqual(reports["fashion"].steps[-1].count, 2)

    def test_missing_segment_key_unknown_bucket(self) -> None:
        sessions = [_sess(["a", "b"])]
        reports = fa.analyse_segmented(sessions, ["a", "b"],
                                          segment_key="niche")
        self.assertIn("unknown", reports)


class TestBestDrop(unittest.TestCase):
    def test_best_drop_picks_worst(self) -> None:
        r1 = fa.FunnelReport(
            bottleneck_step="checkout",
            bottleneck_drop_rate=0.6,
        )
        r2 = fa.FunnelReport(
            bottleneck_step="add_to_cart",
            bottleneck_drop_rate=0.9,
        )
        seg, step, rate = fa.best_drop({"audio": r1, "fashion": r2})
        self.assertEqual(seg, "fashion")
        self.assertEqual(step, "add_to_cart")
        self.assertAlmostEqual(rate, 0.9)

    def test_best_drop_empty(self) -> None:
        seg, step, rate = fa.best_drop({})
        self.assertEqual(seg, "")
        self.assertEqual(rate, 0.0)


class TestHelpers(unittest.TestCase):
    def test_event_kinds_from_dict(self) -> None:
        sess = {"events": [{"kind": "a"}, {"kind": "b"}]}
        self.assertEqual(fa._event_kinds(sess), {"a", "b"})

    def test_event_kinds_from_object(self) -> None:
        class E:
            def __init__(self, k):
                self.kind = k
        class S:
            def __init__(self, kinds):
                self.events = [E(k) for k in kinds]
        self.assertEqual(
            fa._event_kinds(S(["x", "y"])), {"x", "y"},
        )


if __name__ == "__main__":
    unittest.main()
