"""Counter-argument tests."""
from __future__ import annotations

import unittest

from core.brain import counter_argument as ca


class TestCritique(unittest.TestCase):
    def setUp(self) -> None:
        self.eng = ca.CounterArgumentEngine()

    def test_clean_proposal_low_risk(self) -> None:
        r = self.eng.critique({
            "evidence": ["a", "b", "c", "d"],
            "spend_usd": 20,
            "daily_cap_usd": 100,
            "projected_margin_pct": 0.35,
            "min_margin_pct": 0.1,
            "assumptions": [],
            "stakes_band": "low",
        })
        self.assertLess(r.overall_risk, 0.2)

    def test_thin_evidence_flagged(self) -> None:
        r = self.eng.critique({"evidence": []})
        names = [o.probe for o in r.objections]
        self.assertIn("thin_evidence", names)

    def test_high_spend_without_cap(self) -> None:
        r = self.eng.critique({"spend_usd": 500})
        names = [o.probe for o in r.objections]
        self.assertIn("high_spend_without_cap", names)

    def test_novelty_without_canary(self) -> None:
        r = self.eng.critique({"novel": True})
        names = [o.probe for o in r.objections]
        self.assertIn("novelty_without_canary", names)

    def test_margin_floor_breach(self) -> None:
        r = self.eng.critique({
            "projected_margin_pct": 0.05,
            "min_margin_pct": 0.15,
        })
        names = [o.probe for o in r.objections]
        self.assertIn("margin_floor_breach", names)

    def test_assumption_untested(self) -> None:
        r = self.eng.critique({
            "assumptions": ["a1", "a2"],
            "assumptions_tested": ["a1"],
        })
        names = [o.probe for o in r.objections]
        self.assertIn("assumption_untested", names)

    def test_irreversible_without_rollback(self) -> None:
        r = self.eng.critique({"irreversible": True})
        names = [o.probe for o in r.objections]
        self.assertIn("reversibility_missing", names)

    def test_high_stakes_no_counterfactual(self) -> None:
        r = self.eng.critique({"stakes_band": "high"})
        names = [o.probe for o in r.objections]
        self.assertIn("counterfactual_absent", names)


class TestRisk(unittest.TestCase):
    def test_risk_between_0_and_1(self) -> None:
        eng = ca.CounterArgumentEngine()
        r = eng.critique({
            "spend_usd": 500, "novel": True,
            "irreversible": True,
            "projected_margin_pct": 0.01, "min_margin_pct": 0.2,
        })
        self.assertGreaterEqual(r.overall_risk, 0.0)
        self.assertLessEqual(r.overall_risk, 1.0)

    def test_many_high_severity_pushes_risk_up(self) -> None:
        eng = ca.CounterArgumentEngine()
        clean = eng.critique({
            "evidence": ["a", "b", "c"],
            "spend_usd": 10, "projected_margin_pct": 0.5,
            "stakes_band": "low",
        })
        risky = eng.critique({
            "evidence": [],
            "spend_usd": 500,
            "irreversible": True,
            "novel": True,
            "projected_margin_pct": 0.01, "min_margin_pct": 0.2,
            "stakes_band": "high",
        })
        self.assertGreater(risky.overall_risk, clean.overall_risk)


class TestCustomProbe(unittest.TestCase):
    def test_register_and_fire(self) -> None:
        eng = ca.CounterArgumentEngine()
        def always_fires(p):
            yield ca.Objection(
                probe="always", severity="low",
                reason="testing",
            )
        eng.register_probe("always", always_fires)
        r = eng.critique({})
        names = [o.probe for o in r.objections]
        self.assertIn("always", names)

    def test_blank_name_raises(self) -> None:
        eng = ca.CounterArgumentEngine()
        with self.assertRaises(ValueError):
            eng.register_probe("", lambda p: [])

    def test_deregister(self) -> None:
        eng = ca.CounterArgumentEngine()
        self.assertTrue(eng.deregister("thin_evidence"))
        self.assertFalse(eng.deregister("thin_evidence"))

    def test_broken_probe_isolated(self) -> None:
        eng = ca.CounterArgumentEngine()
        def broken(p):
            raise RuntimeError("probe raised")
        eng.register_probe("broken", broken)
        # Should not crash; just skip the broken probe
        r = eng.critique({"spend_usd": 500})
        names = [o.probe for o in r.objections]
        self.assertNotIn("broken", names)
        self.assertIn("high_spend_without_cap", names)


class TestSorting(unittest.TestCase):
    def test_objections_sorted_by_severity(self) -> None:
        eng = ca.CounterArgumentEngine()
        r = eng.critique({
            "spend_usd": 500,         # high
            "assumptions": ["a"],       # medium
        })
        # First objection should be high severity
        if r.objections:
            self.assertEqual(r.objections[0].severity, "high")


if __name__ == "__main__":
    unittest.main()
