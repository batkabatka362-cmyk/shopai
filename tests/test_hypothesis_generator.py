"""Hypothesis generator tests."""
from __future__ import annotations

import unittest

from core.brain import hypothesis_generator as hg


class TestGenerate(unittest.TestCase):
    def setUp(self) -> None:
        self.g = hg.HypothesisGenerator()

    def test_empty_event_none(self) -> None:
        self.assertIsNone(self.g.generate({}))

    def test_drift_event_produces_hypothesis(self) -> None:
        event = {
            "kind": "drift",
            "predictor_id": "roas_model",
            "bias": 0.4,
            "drift_score": 3.0,
        }
        h = self.g.generate(event)
        self.assertIsNotNone(h)
        self.assertEqual(h.kind, "drift")
        self.assertEqual(h.direction, "above")
        self.assertEqual(h.kpi, "roas_model")

    def test_drift_below_threshold_skipped(self) -> None:
        event = {
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.01,
            "drift_score": 1.5,
        }
        self.assertIsNone(self.g.generate(event))

    def test_assumption_violation_produces(self) -> None:
        event = {
            "kind": "assumption_violation",
            "kpi": "cvr",
            "expected_value": 0.02,
            "observed_value": 0.012,
            "assumption_id": "a1",
        }
        h = self.g.generate(event)
        self.assertIsNotNone(h)
        self.assertEqual(h.direction, "below")

    def test_pre_breach_critical(self) -> None:
        event = {
            "kind": "pre_breach",
            "kpi": "cpm",
            "severity": "critical",
            "direction": "above",
            "slope": 0.1,
            "confidence": 0.8,
        }
        h = self.g.generate(event)
        self.assertIsNotNone(h)
        self.assertEqual(h.horizon_days, 1.0)

    def test_pre_breach_info_skipped(self) -> None:
        event = {
            "kind": "pre_breach",
            "kpi": "cpm",
            "severity": "info",
        }
        self.assertIsNone(self.g.generate(event))

    def test_unknown_kind_no_hypothesis(self) -> None:
        self.assertIsNone(
            self.g.generate({"kind": "unknown"}),
        )


class TestDedupe(unittest.TestCase):
    def test_duplicate_signature_returns_same(self) -> None:
        g = hg.HypothesisGenerator()
        event = {
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.4,
            "drift_score": 3.0,
        }
        h1 = g.generate(event)
        h2 = g.generate(event)
        self.assertEqual(h1.id, h2.id)
        self.assertEqual(g.stats()["tracked"], 1)


class TestBatch(unittest.TestCase):
    def test_batch_returns_new_hypotheses(self) -> None:
        g = hg.HypothesisGenerator()
        events = [
            {
                "kind": "drift",
                "predictor_id": "p1",
                "bias": 0.5,
                "drift_score": 3.0,
            },
            {
                "kind": "drift",
                "predictor_id": "p2",
                "bias": -0.4,
                "drift_score": 2.5,
            },
            {"kind": "unknown"},
        ]
        out = g.generate_batch(events)
        self.assertEqual(len(out), 2)


class TestCustomTemplate(unittest.TestCase):
    def test_register_and_fire(self) -> None:
        def trigger(e):
            return e.get("kind") == "custom"

        def builder(e):
            return hg.GeneratedHypothesis(
                id="x", signature="s",
                kind="anomaly",
                subject="x", kpi="x",
                direction="above", magnitude=0.1,
                horizon_days=1.0, rationale="",
                confidence=0.5, source_refs=(), ts=0.0,
            )

        tpl = hg.HypothesisTemplate(
            id="custom", kind="anomaly",
            trigger=trigger, builder=builder,
        )
        g = hg.HypothesisGenerator()
        g.register_template(tpl)
        h = g.generate({"kind": "custom"})
        self.assertIsNotNone(h)
        self.assertEqual(h.kind, "anomaly")

    def test_unregister(self) -> None:
        g = hg.HypothesisGenerator()
        self.assertTrue(g.unregister_template("drift_template"))
        event = {
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.5,
            "drift_score": 3.0,
        }
        self.assertIsNone(g.generate(event))


class TestQueries(unittest.TestCase):
    def test_recent_newest_first(self) -> None:
        g = hg.HypothesisGenerator()
        for i in range(3):
            g.generate({
                "kind": "drift",
                "predictor_id": f"p{i}",
                "bias": 0.4,
                "drift_score": 3.0,
            })
        r = g.recent(limit=3)
        self.assertEqual(len(r), 3)

    def test_by_kind(self) -> None:
        g = hg.HypothesisGenerator()
        g.generate({
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.5,
            "drift_score": 3.0,
        })
        drifts = g.by_kind("drift")
        self.assertEqual(len(drifts), 1)
        self.assertEqual(g.by_kind("pre_breach"), [])


class TestStats(unittest.TestCase):
    def test_stats(self) -> None:
        g = hg.HypothesisGenerator()
        s = g.stats()
        self.assertGreater(s["templates"], 0)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        g = hg.HypothesisGenerator()
        g.generate({
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.5,
            "drift_score": 3.0,
        })
        self.assertEqual(g.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        g = hg.HypothesisGenerator()
        h = g.generate({
            "kind": "drift",
            "predictor_id": "p",
            "bias": 0.5,
            "drift_score": 3.0,
        })
        d = h.as_dict()
        self.assertIn("rationale", d)


if __name__ == "__main__":
    unittest.main()
