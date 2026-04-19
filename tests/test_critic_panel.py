"""Critic panel tests."""
from __future__ import annotations

import unittest

from core.brain import critic_panel as cp


class TestRegistration(unittest.TestCase):
    def test_default_critics_present(self) -> None:
        p = cp.CriticPanel()
        for name in ("bull", "bear", "accountant", "ethicist"):
            self.assertIn(name, p.critics())

    def test_register_custom(self) -> None:
        p = cp.CriticPanel()
        p.register_critic("domain", lambda x: (4.0, "ok"))
        self.assertIn("domain", p.critics())

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            cp.CriticPanel().register_critic("", lambda x: (3, ""))

    def test_zero_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            cp.CriticPanel().register_critic(
                "a", lambda x: (3, ""), weight=0,
            )

    def test_deregister(self) -> None:
        p = cp.CriticPanel()
        self.assertTrue(p.deregister("bull"))
        self.assertFalse(p.deregister("bull"))


class TestGradeVerdicts(unittest.TestCase):
    def test_strong_proposal_approved(self) -> None:
        p = cp.CriticPanel()
        rep = p.grade({
            "projected_roas": 3.0,
            "projected_margin_pct": 0.5,
            "evidence": ["a", "b", "c"],
            "spend_usd": 20,
            "daily_cap_usd": 100,
        })
        self.assertEqual(rep.overall_verdict, "approve")

    def test_deceptive_proposal_rejected(self) -> None:
        p = cp.CriticPanel()
        rep = p.grade({
            "deceptive_anchor": True,
            "scarcity_exaggerated": True,
            "irreversible": True,
        })
        self.assertEqual(rep.overall_verdict, "reject")

    def test_weak_evidence_gets_revise(self) -> None:
        p = cp.CriticPanel()
        rep = p.grade({
            "projected_roas": 1.5,
            "projected_margin_pct": 0.2,
            "evidence": [],
            "spend_usd": 20,
        })
        self.assertIn(rep.overall_verdict, ("revise", "reject"))

    def test_grades_bounded_0_to_5(self) -> None:
        p = cp.CriticPanel()
        rep = p.grade({"projected_roas": 10, "projected_margin_pct": 0.9})
        for g in rep.critic_grades:
            self.assertGreaterEqual(g.grade, 0.0)
            self.assertLessEqual(g.grade, 5.0)


class TestBull(unittest.TestCase):
    def test_high_roas_bull_positive(self) -> None:
        g, _ = cp._bull({"projected_roas": 3.0})
        self.assertGreater(g, 2.5)


class TestBear(unittest.TestCase):
    def test_irreversible_without_rollback_bear_negative(self) -> None:
        g, _ = cp._bear({"irreversible": True})
        self.assertLess(g, 2.5)

    def test_low_roas_bear_negative(self) -> None:
        g, _ = cp._bear({
            "projected_roas": 0.3, "evidence": ["a"],
        })
        self.assertLess(g, 2.5)


class TestAccountant(unittest.TestCase):
    def test_margin_below_floor_penalised(self) -> None:
        g, _ = cp._accountant({
            "projected_margin_pct": 0.05,
            "min_margin_pct": 0.15,
        })
        self.assertLess(g, 2.5)

    def test_healthy_margin_praised(self) -> None:
        g, _ = cp._accountant({
            "projected_margin_pct": 0.5,
        })
        self.assertGreater(g, 2.5)

    def test_uncapped_spend_penalised(self) -> None:
        g, _ = cp._accountant({"spend_usd": 500})
        self.assertLess(g, 2.5)


class TestEthicist(unittest.TestCase):
    def test_clean_proposal_high_grade(self) -> None:
        g, _ = cp._ethicist({})
        self.assertGreaterEqual(g, 3.5)

    def test_deceptive_anchor_flagged(self) -> None:
        g, _ = cp._ethicist({"deceptive_anchor": True})
        self.assertLess(g, 2.0)


class TestEdgeCases(unittest.TestCase):
    def test_broken_critic_isolated(self) -> None:
        p = cp.CriticPanel()
        def broken(proposal):
            raise RuntimeError("bad")
        p.register_critic("broken", broken)
        rep = p.grade({"projected_roas": 2.0,
                        "projected_margin_pct": 0.4,
                        "evidence": ["a"]})
        names = [g.name for g in rep.critic_grades]
        self.assertNotIn("broken", names)

    def test_all_critics_broken_empty_grades(self) -> None:
        p = cp.CriticPanel()
        # Deregister every default
        for n in ("bull", "bear", "accountant", "ethicist"):
            p.deregister(n)
        rep = p.grade({})
        self.assertEqual(rep.critic_grades, [])
        self.assertEqual(rep.avg_grade, 0.0)


class TestAsDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        p = cp.CriticPanel()
        rep = p.grade({"projected_roas": 2.0,
                        "projected_margin_pct": 0.4})
        d = rep.as_dict()
        for key in ("avg_grade", "min_grade", "overall_verdict",
                     "critic_grades"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
