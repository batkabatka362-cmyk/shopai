"""Owner model tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import owner_model as om


class TestCold(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = om.OwnerModel(Path(self._tmp.name) / "om.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_cold_start_neutral(self) -> None:
        p = self.m.preferences()
        self.assertEqual(p.n_feedback, 0)
        # Laplace priors → all mid-range
        self.assertAlmostEqual(p.risk_tolerance, 0.5)
        self.assertAlmostEqual(p.autonomy_tolerance, 0.5)
        self.assertAlmostEqual(p.growth_preference, 0.5)

    def test_weights_sum_to_one(self) -> None:
        w = self.m.weights()
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = om.OwnerModel(Path(self._tmp.name) / "om.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record(action_kind="", approved=True)

    def test_single_row_counts(self) -> None:
        self.m.record(action_kind="scale_budget", approved=True)
        self.assertEqual(self.m.preferences().n_feedback, 1)


class TestRisk(unittest.TestCase):
    def test_bold_approvals_raise_risk_tolerance(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(action_kind="scale", approved=True, bold=True)
        prefs = m.preferences()
        self.assertGreater(prefs.risk_tolerance, 0.8)
        m.close()
        tmp.cleanup()

    def test_bold_rejections_lower_risk_tolerance(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(action_kind="scale", approved=False, bold=True)
        prefs = m.preferences()
        self.assertLess(prefs.risk_tolerance, 0.2)
        m.close()
        tmp.cleanup()


class TestAutonomy(unittest.TestCase):
    def test_fast_approvals_raise_autonomy(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(
                action_kind="set_price", approved=True,
                latency_s=0.0,
            )
        prefs = m.preferences()
        self.assertGreater(prefs.autonomy_tolerance, 0.8)
        m.close()
        tmp.cleanup()

    def test_slow_reviews_lower_autonomy(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(
                action_kind="set_price", approved=True,
                latency_s=3600.0,   # 1 hour review
            )
        prefs = m.preferences()
        self.assertLess(prefs.autonomy_tolerance, 0.2)
        # velocity_h should reflect the 1h review
        self.assertGreater(prefs.velocity_h, 0.5)
        m.close()
        tmp.cleanup()


class TestGrowth(unittest.TestCase):
    def test_scale_approvals_raise_growth_preference(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(action_kind="scale_budget", approved=True)
        prefs = m.preferences()
        self.assertGreater(prefs.growth_preference, 0.8)
        m.close()
        tmp.cleanup()

    def test_non_scale_actions_dont_move_growth(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(action_kind="refund", approved=True)
        prefs = m.preferences()
        self.assertAlmostEqual(prefs.growth_preference, 0.5)
        m.close()
        tmp.cleanup()


class TestCost(unittest.TestCase):
    def test_expensive_rejections_raise_cost_sensitivity(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(
                action_kind="buy_ads", approved=False,
                cost_usd=100.0,
            )
        prefs = m.preferences()
        self.assertGreater(prefs.cost_sensitivity, 0.7)
        m.close()
        tmp.cleanup()

    def test_cheap_rejections_move_cost_sensitivity_less(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(10):
            m.record(
                action_kind="tag_product", approved=False,
                cost_usd=0.01,
            )
        prefs = m.preferences()
        # Cheap rejections shouldn't over-blame cost
        self.assertLess(prefs.cost_sensitivity, 0.55)
        m.close()
        tmp.cleanup()


class TestWeights(unittest.TestCase):
    def test_aggressive_owner_favours_roas(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        # Owner approves all scale actions, none else
        for _ in range(20):
            m.record(action_kind="scale", approved=True, bold=True)
        weights = m.weights()
        self.assertGreater(weights["roas"], weights["stability"])
        m.close()
        tmp.cleanup()

    def test_cautious_owner_favours_refund_control(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        for _ in range(20):
            m.record(action_kind="bold_move", approved=False, bold=True)
        weights = m.weights()
        # Low risk tolerance → more weight on refund_rate
        self.assertGreater(weights["refund_rate"], 0.25)
        m.close()
        tmp.cleanup()


class TestClear(unittest.TestCase):
    def test_clear_resets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        m.record(action_kind="x", approved=True)
        n = m.clear()
        self.assertEqual(n, 1)
        self.assertEqual(m.preferences().n_feedback, 0)
        m.close()
        tmp.cleanup()


class TestSummary(unittest.TestCase):
    def test_summary_shape(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = om.OwnerModel(Path(tmp.name) / "om.db")
        s = m.summary()
        self.assertIn("preferences", s)
        self.assertIn("weights", s)
        self.assertIn("risk_tolerance", s["preferences"])
        m.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_preferences_as_dict(self) -> None:
        p = om.Preferences(
            risk_tolerance=0.5, autonomy_tolerance=0.5,
            cost_sensitivity=0.5, growth_preference=0.5,
            velocity_h=1.0, n_feedback=3,
        )
        d = p.as_dict()
        self.assertEqual(d["n_feedback"], 3)


if __name__ == "__main__":
    unittest.main()
