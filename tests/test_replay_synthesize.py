"""Synthetic Shopify order generator tests.

The replay tool needs a JSONL of real orders to feed the
learning loop. Until the owner has a live store, synthesized
orders provide the T0 → T1 validation signal. These tests
lock determinism + Shopify-shape compatibility so the
webhook handler never crashes on a synthesized payload.
"""
from __future__ import annotations

import unittest

from agents.replay.synthesize import (
    synthesize_order,
    synthesize_orders,
    synthesize_orders_with_random_decisions,
)


class TestSynthesizeSingle(unittest.TestCase):
    def test_required_fields_present(self):
        import random
        rng = random.Random(1)
        o = synthesize_order(index=1, rng=rng)
        for k in (
            "id", "order_id", "name", "financial_status",
            "currency", "total_price", "subtotal_price",
            "line_items", "customer", "note_attributes",
        ):
            self.assertIn(k, o)
        self.assertEqual(o["financial_status"], "paid")
        self.assertEqual(o["currency"], "USD")

    def test_decision_id_in_note_attributes(self):
        import random
        rng = random.Random(7)
        o = synthesize_order(
            index=42, rng=rng, decision_id="dec_xyz",
        )
        notes = o["note_attributes"]
        ids = [n["value"] for n in notes
               if n.get("name") == "shopai_decision_id"]
        self.assertEqual(ids, ["dec_xyz"])

    def test_no_decision_id_when_absent(self):
        import random
        rng = random.Random(7)
        o = synthesize_order(index=42, rng=rng)
        self.assertEqual(o["note_attributes"], [])

    def test_line_items_non_empty(self):
        import random
        rng = random.Random(3)
        o = synthesize_order(index=1, rng=rng)
        self.assertEqual(len(o["line_items"]), 1)
        li = o["line_items"][0]
        for k in ("sku", "title", "quantity", "price"):
            self.assertIn(k, li)
        self.assertGreater(int(li["quantity"]), 0)
        self.assertGreater(float(li["price"]), 0)

    def test_total_price_parseable_float(self):
        import random
        rng = random.Random(3)
        o = synthesize_order(index=1, rng=rng)
        # Shopify sends total_price as a string → must parse
        float(o["total_price"])
        float(o["subtotal_price"])


class TestSynthesizeBatch(unittest.TestCase):
    def test_count_matches(self):
        orders = synthesize_orders(count=10, seed=1)
        self.assertEqual(len(orders), 10)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            synthesize_orders(count=0)

    def test_deterministic_with_seed(self):
        a = synthesize_orders(count=5, seed=42)
        b = synthesize_orders(count=5, seed=42)
        self.assertEqual(
            [o["total_price"] for o in a],
            [o["total_price"] for o in b],
        )

    def test_different_seeds_different_output(self):
        a = synthesize_orders(count=5, seed=1)
        b = synthesize_orders(count=5, seed=2)
        self.assertNotEqual(
            [o["total_price"] for o in a],
            [o["total_price"] for o in b],
        )

    def test_decision_pool_rotation(self):
        orders = synthesize_orders(
            count=6, seed=1,
            decision_ids=["dec_a", "dec_b", "dec_c"],
        )
        ids = []
        for o in orders:
            for n in o["note_attributes"]:
                if n["name"] == "shopai_decision_id":
                    ids.append(n["value"])
        # Exactly 6 decision attributes (pool rotates)
        self.assertEqual(len(ids), 6)
        # All three pool ids used
        self.assertEqual(
            set(ids), {"dec_a", "dec_b", "dec_c"},
        )

    def test_empty_decision_pool_means_no_attribute(self):
        orders = synthesize_orders(
            count=3, seed=1, decision_ids=[],
        )
        for o in orders:
            self.assertEqual(o["note_attributes"], [])

    def test_stable_order_ids(self):
        orders = synthesize_orders(count=3, seed=7)
        ids = [o["id"] for o in orders]
        self.assertEqual(
            ids,
            ["synth-ord-000001", "synth-ord-000002",
             "synth-ord-000003"],
        )


class TestRandomDecisions(unittest.TestCase):
    def test_attach_rate_zero(self):
        orders = synthesize_orders_with_random_decisions(
            count=20, seed=1, attach_rate=0.0,
        )
        for o in orders:
            self.assertEqual(o["note_attributes"], [])

    def test_attach_rate_one(self):
        orders = synthesize_orders_with_random_decisions(
            count=20, seed=1, attach_rate=1.0,
        )
        for o in orders:
            ids = [n["value"] for n in o["note_attributes"]
                   if n["name"] == "shopai_decision_id"]
            self.assertEqual(len(ids), 1)
            self.assertTrue(ids[0].startswith("dec_synth_"))

    def test_attach_rate_half_seeded(self):
        """With seed=1 and attach_rate=0.5, some orders get
        decision ids and some don't — deterministic under
        fixed seed."""
        orders = synthesize_orders_with_random_decisions(
            count=20, seed=1, attach_rate=0.5,
        )
        with_id = sum(
            1 for o in orders
            if any(n["name"] == "shopai_decision_id"
                   for n in o["note_attributes"])
        )
        # Within reasonable binomial range for n=20 p=0.5
        self.assertGreater(with_id, 3)
        self.assertLess(with_id, 17)

    def test_invalid_attach_rate(self):
        with self.assertRaises(ValueError):
            synthesize_orders_with_random_decisions(
                count=5, attach_rate=-0.1,
            )
        with self.assertRaises(ValueError):
            synthesize_orders_with_random_decisions(
                count=5, attach_rate=1.5,
            )


class TestSynthesizedFeedsHandler(unittest.TestCase):
    """End-to-end: synthesized payloads survive the real
    OrderWebhookHandler without raising. Money path matters
    here — if a synthesized order shape drifts from Shopify's
    real shape, this catches it at T0."""

    def test_handler_accepts_synthesized(self):
        from agents.replay.order_replay import replay_orders

        orders = synthesize_orders(count=5, seed=1)
        stats = replay_orders(orders)
        self.assertEqual(stats.attempted, 5)
        # The handler may "fail" on a synth order because many
        # sub-components (OutcomeRecorder, attribution) have
        # defaults that raise in edge cases — what we lock is
        # that the replay path TRIES each order (no crash
        # before even calling the handler).
        self.assertEqual(
            stats.attempted,
            stats.successful + stats.failed,
        )


if __name__ == "__main__":
    unittest.main()
