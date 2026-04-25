"""Safety envelope tests."""
from __future__ import annotations

import unittest

from core.brain import safety_envelope as sf


class TestAdmits(unittest.TestCase):
    def test_numeric_range_within(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (0, 100)})
        self.assertTrue(env.admits({"p": 50}))

    def test_numeric_range_outside(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (0, 100)})
        self.assertFalse(env.admits({"p": 500}))

    def test_allowed_value_match(self) -> None:
        env = sf.Envelope(
            allowed_values={"tone": frozenset({"friendly", "luxury"})},
        )
        self.assertTrue(env.admits({"tone": "luxury"}))
        self.assertFalse(env.admits({"tone": "clickbait"}))

    def test_forbidden_field_present(self) -> None:
        env = sf.Envelope(forbidden_fields=frozenset({"banned"}))
        self.assertFalse(env.admits({"banned": "x"}))
        self.assertTrue(env.admits({"allowed": "x"}))

    def test_numeric_non_numeric_rejected(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (0, 100)})
        self.assertFalse(env.admits({"p": "foo"}))

    def test_missing_field_admitted(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (0, 10)})
        # field absent → envelope doesn't constrain, admits
        self.assertTrue(env.admits({"other": 1}))


class TestProject(unittest.TestCase):
    def test_clamps_above_max(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (0, 100)})
        self.assertEqual(env.project({"p": 500})["p"], 100)

    def test_clamps_below_min(self) -> None:
        env = sf.Envelope(numeric_ranges={"p": (10, 100)})
        self.assertEqual(env.project({"p": 5})["p"], 10)

    def test_drops_forbidden_field(self) -> None:
        env = sf.Envelope(forbidden_fields=frozenset({"banned"}))
        out = env.project({"banned": "x", "ok": "y"})
        self.assertNotIn("banned", out)
        self.assertEqual(out["ok"], "y")

    def test_forces_allowed_string(self) -> None:
        env = sf.Envelope(
            allowed_values={"tone": frozenset({"friendly"})},
        )
        out = env.project({"tone": "clickbait"})
        self.assertEqual(out["tone"], "friendly")

    def test_picks_closest_numeric_allowed(self) -> None:
        env = sf.Envelope(
            allowed_values={"tier": frozenset({1, 5, 10})},
        )
        out = env.project({"tier": 6})
        self.assertEqual(out["tier"], 5)


class TestIntersect(unittest.TestCase):
    def test_tighter_bounds_win(self) -> None:
        a = sf.Envelope(numeric_ranges={"p": (0, 100)})
        b = sf.Envelope(numeric_ranges={"p": (10, 50)})
        merged = a.intersect(b)
        self.assertEqual(merged.numeric_ranges["p"], (10, 50))

    def test_allowed_values_intersect(self) -> None:
        a = sf.Envelope(
            allowed_values={"tone": frozenset({"a", "b", "c"})},
        )
        b = sf.Envelope(
            allowed_values={"tone": frozenset({"b", "c", "d"})},
        )
        merged = a.intersect(b)
        self.assertEqual(merged.allowed_values["tone"], frozenset({"b", "c"}))

    def test_forbidden_union(self) -> None:
        a = sf.Envelope(forbidden_fields=frozenset({"x"}))
        b = sf.Envelope(forbidden_fields=frozenset({"y"}))
        merged = a.intersect(b)
        self.assertEqual(merged.forbidden_fields, frozenset({"x", "y"}))


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        sf.clear_rules()

    def tearDown(self) -> None:
        sf.clear_rules()

    def test_low_cash_tightens_envelope(self) -> None:
        sf.register_rule(
            predicate=lambda ctx: ctx.get("cash_band") == "low",
            builder=lambda ctx: sf.Envelope(
                numeric_ranges={"daily_spend_usd": (0, 20)},
            ),
        )
        env = sf.envelope_for(
            {"cash_band": "low"},
            base=sf.default_global_envelope(),
        )
        self.assertEqual(env.numeric_ranges["daily_spend_usd"], (0.0, 20))

    def test_non_matching_rule_skipped(self) -> None:
        sf.register_rule(
            predicate=lambda ctx: ctx.get("cash_band") == "low",
            builder=lambda ctx: sf.Envelope(
                numeric_ranges={"daily_spend_usd": (0, 5)},
            ),
        )
        env = sf.envelope_for({"cash_band": "high"},
                               base=sf.default_global_envelope())
        self.assertEqual(
            env.numeric_ranges["daily_spend_usd"],
            (0.0, 500.0),
        )

    def test_failing_predicate_doesnt_break(self) -> None:
        sf.register_rule(
            predicate=lambda ctx: ctx["required_field"] == "yes",
            builder=lambda ctx: sf.Envelope(
                forbidden_fields=frozenset({"anything"}),
            ),
        )
        # Context doesn't have 'required_field' — predicate raises
        # KeyError; envelope_for should swallow and return base.
        env = sf.envelope_for({}, base=sf.default_global_envelope())
        self.assertIn("daily_spend_usd", env.numeric_ranges)


class TestDefaultGlobal(unittest.TestCase):
    def test_defaults_sensible(self) -> None:
        env = sf.default_global_envelope()
        self.assertIn("currency", env.allowed_values)
        self.assertEqual(env.numeric_ranges["discount_pct"], (0.0, 70.0))

    def test_admits_normal_action(self) -> None:
        env = sf.default_global_envelope()
        self.assertTrue(env.admits({
            "daily_spend_usd": 50,
            "price_usd": 29.99,
            "currency": "USD",
        }))

    def test_rejects_over_cap_spend(self) -> None:
        env = sf.default_global_envelope()
        self.assertFalse(env.admits({"daily_spend_usd": 10_000}))


if __name__ == "__main__":
    unittest.main()
