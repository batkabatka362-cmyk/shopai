"""Action safety guard tests."""
from __future__ import annotations

import unittest

from core.brain import action_safety_guard as asg


class TestBrightLine(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            asg.BrightLine(name="", predicate=lambda a: False)

    def test_fires_on_match(self) -> None:
        rule = asg.BrightLine(
            name="r", predicate=lambda a: a.get("x") == 1,
        )
        self.assertTrue(rule.fires({"x": 1}))
        self.assertFalse(rule.fires({"x": 2}))

    def test_raise_treated_as_firing(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        rule = asg.BrightLine(name="r", predicate=boom)
        # Fail closed
        self.assertTrue(rule.fires({}))


class TestScopeClassify(unittest.TestCase):
    def test_single_batch_bulk_global(self) -> None:
        self.assertEqual(asg._classify_scope(1), "single")
        self.assertEqual(asg._classify_scope(10), "batch")
        self.assertEqual(asg._classify_scope(100), "bulk")
        self.assertEqual(asg._classify_scope(1000), "global")


class TestBrightLineBlocking(unittest.TestCase):
    def test_order_delete_blocked(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.never_delete_orders())
        v = g.evaluate({"kind": "delete", "target": "order:123"})
        self.assertEqual(v.verdict, "block")
        self.assertTrue(
            any("never_delete_orders" in r for r in v.reasons),
        )

    def test_currency_change_blocked(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.never_change_currency())
        v = g.evaluate({"kind": "update", "field": "store.currency"})
        self.assertEqual(v.verdict, "block")

    def test_ads_spend_cap(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.daily_ads_cap(max_usd=20))
        over = g.evaluate(
            {"target_kind": "ads", "budget_change_usd": 50},
        )
        self.assertEqual(over.verdict, "block")
        under = g.evaluate(
            {"target_kind": "ads", "budget_change_usd": 5},
        )
        self.assertEqual(under.verdict, "allow")


class TestBlastRadius(unittest.TestCase):
    def test_single_allows(self) -> None:
        g = asg.ActionSafetyGuard()
        v = g.evaluate({"kind": "set_price", "records_touched": 1})
        self.assertEqual(v.verdict, "allow")

    def test_bulk_requires_approval(self) -> None:
        g = asg.ActionSafetyGuard()
        v = g.evaluate({"kind": "set_price", "records_touched": 100})
        self.assertEqual(v.verdict, "require_approval")

    def test_global_blocks_by_default(self) -> None:
        g = asg.ActionSafetyGuard()
        v = g.evaluate({"kind": "set_price", "records_touched": 10_000})
        self.assertEqual(v.verdict, "block")

    def test_batch_can_be_approved(self) -> None:
        g = asg.ActionSafetyGuard(batch_requires_approval=True)
        v = g.evaluate({"kind": "update", "records_touched": 10})
        self.assertEqual(v.verdict, "require_approval")

    def test_explicit_blast_overrides(self) -> None:
        g = asg.ActionSafetyGuard()
        explicit = asg.BlastRadius(
            records_touched=3, scope="single", reversible=True,
        )
        v = g.evaluate(
            {"kind": "set_price", "records_touched": 9999},
            blast=explicit,
        )
        self.assertEqual(v.verdict, "allow")


class TestRollback(unittest.TestCase):
    def test_rollback_known_allows_with_low_conf(self) -> None:
        g = asg.ActionSafetyGuard()
        g.register_rollback(
            "set_price",
            steps=["restore prior price"],
            last_tested_days=3,
        )
        v = g.evaluate(
            {"kind": "set_price", "reversible": True},
            confidence=0.5,
        )
        self.assertEqual(v.verdict, "allow")
        self.assertTrue(v.rollback_known)

    def test_irreversible_low_conf_requires_approval(self) -> None:
        g = asg.ActionSafetyGuard()
        v = g.evaluate(
            {"kind": "set_price", "reversible": False},
            confidence=0.5,
        )
        self.assertEqual(v.verdict, "require_approval")

    def test_irreversible_high_conf_allows(self) -> None:
        g = asg.ActionSafetyGuard()
        g.register_rollback(
            "set_price", steps=["restore"],
            last_tested_days=5,
        )
        v = g.evaluate(
            {"kind": "set_price", "reversible": False},
            confidence=0.95,
        )
        # Known rollback + high confidence, even if flagged as
        # irreversible, is permitted.
        self.assertEqual(v.verdict, "allow")

    def test_stale_rollback_requires_approval(self) -> None:
        g = asg.ActionSafetyGuard()
        g.register_rollback(
            "set_price", steps=["restore"],
            last_tested_days=365,
        )
        v = g.evaluate({"kind": "set_price"}, confidence=0.99)
        self.assertEqual(v.verdict, "require_approval")

    def test_blank_rollback_rejected(self) -> None:
        g = asg.ActionSafetyGuard()
        with self.assertRaises(ValueError):
            g.register_rollback("", steps=["x"])
        with self.assertRaises(ValueError):
            g.register_rollback("set_price", steps=[])


class TestStrictest(unittest.TestCase):
    def test_block_wins_over_approval(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.never_delete_orders())
        v = g.evaluate(
            {"kind": "delete", "target": "order:1",
             "records_touched": 100},
        )
        # Bright-line block beats the bulk-requires-approval verdict
        self.assertEqual(v.verdict, "block")


class TestStatsAndDict(unittest.TestCase):
    def test_stats(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.never_delete_orders())
        g.register_rollback("x", steps=["y"])
        s = g.stats()
        self.assertEqual(s["bright_lines"], 1)
        self.assertEqual(s["rollback_recipes"], 1)

    def test_verdict_as_dict(self) -> None:
        g = asg.ActionSafetyGuard()
        v = g.evaluate({"kind": "x"})
        d = v.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("blast", d)


class TestClear(unittest.TestCase):
    def test_clear_bright_lines(self) -> None:
        g = asg.ActionSafetyGuard()
        g.add_bright_line(asg.never_delete_orders())
        g.clear_bright_lines()
        self.assertEqual(g.bright_lines(), [])


if __name__ == "__main__":
    unittest.main()
