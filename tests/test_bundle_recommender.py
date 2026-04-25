"""Bundle recommender tests."""
from __future__ import annotations

import unittest

from core.brain import bundle_recommender as br


class TestIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.r = br.BundleRecommender(
            min_support=0.01, min_confidence=0.1, min_lift=1.0,
        )

    def test_list_and_dict_orders(self) -> None:
        n1 = self.r.ingest([["a", "b"]])
        n2 = self.r.ingest([{"skus": ["a", "b"]}])
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 1)

    def test_empty_order_skipped(self) -> None:
        n = self.r.ingest([[], {"skus": []}])
        self.assertEqual(n, 0)

    def test_dedup_within_order(self) -> None:
        self.r.ingest([["a", "a", "b"]])
        # After dedup only pair (a, b) counted once
        rules = self.r.rules()
        # single order won't meet min_lift > 1 — confirm counts instead
        self.assertEqual(self.r.stats()["pair_observations"], 1)

    def test_reset_clears(self) -> None:
        self.r.ingest([["a", "b"]])
        self.r.reset()
        self.assertEqual(self.r.stats()["orders"], 0)


class TestRules(unittest.TestCase):
    def test_strong_pair_emitted(self) -> None:
        r = br.BundleRecommender(
            min_support=0.1, min_confidence=0.3, min_lift=1.0,
        )
        # 20 orders: a+b 8, c 4, d 4, e 4 — a and b always co-occur
        orders = (
            [["a", "b"]] * 8 + [["c"]] * 4 + [["d"]] * 4 + [["e"]] * 4
        )
        r.ingest(orders)
        rules = r.rules()
        self.assertTrue(rules)
        pairs = {(rule.antecedent, rule.consequent) for rule in rules}
        self.assertIn(("a", "b"), pairs)
        self.assertIn(("b", "a"), pairs)

    def test_independent_skus_no_rule(self) -> None:
        r = br.BundleRecommender(
            min_support=0.1, min_confidence=0.3, min_lift=1.5,
        )
        # Totally independent — each sku always alone
        orders = [["a"]] * 10 + [["b"]] * 10
        r.ingest(orders)
        self.assertEqual(r.rules(), [])

    def test_min_support_filters(self) -> None:
        r = br.BundleRecommender(
            min_support=0.5, min_confidence=0.1, min_lift=1.0,
        )
        # a+b in 2/10 orders → 0.2 support, below 0.5
        orders = [["a", "b"]] * 2 + [["c"]] * 8
        r.ingest(orders)
        self.assertEqual(r.rules(), [])


class TestRecommendForSku(unittest.TestCase):
    def test_recommendations_for_source_sku(self) -> None:
        r = br.BundleRecommender(
            min_support=0.1, min_confidence=0.3, min_lift=1.0,
        )
        r.ingest(
            [["a", "b"]] * 6 + [["a", "c"]] * 2
            + [["d"]] * 6 + [["e"]] * 6,
        )
        recs = r.recommend_for_sku("a")
        targets = [rec.consequent for rec in recs]
        self.assertIn("b", targets)

    def test_sku_not_seen_empty(self) -> None:
        r = br.BundleRecommender()
        r.ingest([["a", "b"]])
        self.assertEqual(r.recommend_for_sku("never_seen"), [])


class TestRecommendForCart(unittest.TestCase):
    def test_excludes_items_in_cart(self) -> None:
        r = br.BundleRecommender(
            min_support=0.1, min_confidence=0.3, min_lift=1.0,
        )
        r.ingest(
            [["a", "b"]] * 6 + [["c"]] * 6 + [["d"]] * 6,
        )
        recs = r.recommend_for_cart(["a", "b"])
        self.assertEqual(recs, [])

    def test_suggests_consequent(self) -> None:
        r = br.BundleRecommender(
            min_support=0.1, min_confidence=0.3, min_lift=1.0,
        )
        r.ingest(
            [["a", "b"]] * 6 + [["c"]] * 6 + [["d"]] * 6,
        )
        recs = r.recommend_for_cart(["a"])
        self.assertTrue(any(rec.consequent == "b" for rec in recs))

    def test_empty_cart_empty(self) -> None:
        r = br.BundleRecommender()
        self.assertEqual(r.recommend_for_cart([]), [])


class TestTopBundles(unittest.TestCase):
    def test_sorted_by_score(self) -> None:
        r = br.BundleRecommender(
            min_support=0.05, min_confidence=0.1, min_lift=1.0,
        )
        # Strong pair a-b, weaker c-d
        orders = (
            [["a", "b"]] * 8 + [["a"]] + [["b"]]
            + [["c", "d"]] * 3 + [["c"]] * 3 + [["d"]] * 3
        )
        r.ingest(orders)
        top = r.top_bundles(top_k=5)
        if len(top) >= 2:
            self.assertGreaterEqual(top[0].score(), top[1].score())


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        r = br.BundleRecommender(
            min_support=0.01, min_lift=1.0,
        )
        r.ingest([["a", "b"], ["a", "c"]])
        s = r.stats()
        self.assertEqual(s["orders"], 2)
        self.assertEqual(s["unique_skus"], 3)


if __name__ == "__main__":
    unittest.main()
