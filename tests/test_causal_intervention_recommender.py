"""Causal intervention recommender tests."""
from __future__ import annotations

import unittest

from core.brain import causal_intervention_recommender as cir


class TestIntervention(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            cir.Intervention(name="", feature="x", delta=1.0)

    def test_blank_feature_raises(self) -> None:
        with self.assertRaises(ValueError):
            cir.Intervention(name="x", feature="", delta=1.0)

    def test_negative_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            cir.Intervention(
                name="x", feature="y", delta=1.0, cost_usd=-1,
            )


class TestConfig(unittest.TestCase):
    def test_bad_cost_scale_raises(self) -> None:
        with self.assertRaises(ValueError):
            cir.CausalInterventionRecommender(cost_scale=0)

    def test_bad_side_effect_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            cir.CausalInterventionRecommender(side_effect_weight=-1)


class TestRecommend(unittest.TestCase):
    def setUp(self) -> None:
        # driver weights: spend → revenue = 0.8, price → revenue = -0.4
        self.weights = {
            ("spend", "revenue"): 0.8,
            ("price", "revenue"): -0.4,
            ("spend", "refunds"): 0.1,
        }

        def lookup(feature, kpi):
            return self.weights.get((feature, kpi), 0.0)

        self.rec = cir.CausalInterventionRecommender(
            driver_weight_fn=lookup,
        )

    def test_best_intervention_for_up_direction(self) -> None:
        iv = [
            cir.Intervention(
                name="raise_spend", feature="spend", delta=10.0,
            ),
            cir.Intervention(
                name="drop_price", feature="price", delta=-5.0,
            ),
        ]
        ranked = self.rec.recommend(iv, kpi="revenue")
        # raise_spend impact = 0.8*10 = 8; drop_price = -0.4*-5 = 2
        self.assertEqual(ranked[0].intervention.name, "raise_spend")

    def test_direction_down_flips_sign(self) -> None:
        iv = [
            cir.Intervention(
                name="raise_spend", feature="spend", delta=10.0,
            ),
            cir.Intervention(
                name="cut_spend", feature="spend", delta=-10.0,
            ),
        ]
        ranked = self.rec.recommend(
            iv, kpi="revenue", direction="down",
        )
        self.assertEqual(ranked[0].intervention.name, "cut_spend")

    def test_no_driver_weight_confidence_zero(self) -> None:
        iv = [
            cir.Intervention(
                name="unknown", feature="mystery", delta=1.0,
            ),
        ]
        ranked = self.rec.recommend(iv, kpi="revenue")
        self.assertEqual(ranked[0].confidence, 0.0)

    def test_confident_winner_beats_unknown(self) -> None:
        iv = [
            cir.Intervention(
                name="mystery", feature="mystery", delta=1000.0,
            ),
            cir.Intervention(
                name="tiny_spend", feature="spend", delta=0.1,
            ),
        ]
        ranked = self.rec.recommend(iv, kpi="revenue")
        # "mystery" has huge raw numbers but zero confidence →
        # confident "tiny_spend" surfaces first
        self.assertEqual(ranked[0].intervention.name, "tiny_spend")

    def test_cost_penalises_high_spend(self) -> None:
        iv = [
            cir.Intervention(
                name="cheap", feature="spend", delta=1.0,
                cost_usd=0.0,
            ),
            cir.Intervention(
                name="expensive", feature="spend", delta=1.0,
                cost_usd=100.0,
            ),
        ]
        ranked = self.rec.recommend(iv, kpi="revenue")
        self.assertEqual(ranked[0].intervention.name, "cheap")

    def test_side_effect_penalty_applied(self) -> None:
        # Two options with same target impact but one has a side-effect
        iv = [
            cir.Intervention(
                name="clean", feature="spend", delta=10.0,
            ),
            cir.Intervention(
                name="dirty", feature="spend", delta=10.0,
                side_effects={"refunds": 20.0},
            ),
        ]
        ranked = self.rec.recommend(iv, kpi="revenue")
        self.assertEqual(ranked[0].intervention.name, "clean")

    def test_driver_fn_raise_safe(self) -> None:
        def boom(_f, _k):
            raise RuntimeError("x")

        r = cir.CausalInterventionRecommender(driver_weight_fn=boom)
        iv = [cir.Intervention(name="x", feature="y", delta=1.0)]
        # Should not raise — weight treated as 0
        ranked = r.recommend(iv, kpi="revenue")
        self.assertEqual(ranked[0].confidence, 0.0)

    def test_blank_kpi_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.rec.recommend([], kpi="")

    def test_bad_direction_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.rec.recommend([], kpi="x", direction="sideways")  # type: ignore

    def test_bad_top_k_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.rec.recommend([], kpi="x", top_k=0)


class TestBest(unittest.TestCase):
    def test_best_picks_top(self) -> None:
        def lookup(f, k):
            return 0.9 if f == "spend" else 0.0

        r = cir.CausalInterventionRecommender(driver_weight_fn=lookup)
        iv = [
            cir.Intervention(name="a", feature="spend", delta=1),
            cir.Intervention(name="b", feature="spend", delta=10),
        ]
        self.assertEqual(r.best(iv, kpi="x").intervention.name, "b")

    def test_best_none_empty(self) -> None:
        r = cir.CausalInterventionRecommender()
        self.assertIsNone(r.best([], kpi="x"))


class TestDict(unittest.TestCase):
    def test_intervention_and_recommendation_serialise(self) -> None:
        def lookup(f, k):
            return 0.5

        r = cir.CausalInterventionRecommender(driver_weight_fn=lookup)
        iv = [
            cir.Intervention(
                name="x", feature="y", delta=1.0,
                side_effects={"k2": 0.5},
            ),
        ]
        rec = r.recommend(iv, kpi="k")[0]
        d = rec.as_dict()
        self.assertIn("intervention", d)
        self.assertIn("confidence", d)


if __name__ == "__main__":
    unittest.main()
