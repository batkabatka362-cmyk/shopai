"""Robustness tester tests."""
from __future__ import annotations

import unittest

from core.brain import robustness as rb


def _fragile_rule(payload):
    # crashes on None niche
    return {"score": len(payload["niche"]) * payload["price"]}


def _robust_rule(payload):
    # Clamps into [0, 100] range so adversarial inputs don't swing
    # the output drastically.
    n = payload.get("niche") or ""
    p = payload.get("price") or 0
    try:
        raw = len(str(n)) * float(p)
    except (TypeError, ValueError):
        raw = 0
    return {"score": max(0.0, min(100.0, raw))}


class TestPerturbations(unittest.TestCase):
    def test_drop_field_removes(self) -> None:
        out = rb.drop_field({"a": 1, "b": 2}, "a")
        self.assertNotIn("a", out)

    def test_null_field_sets_none(self) -> None:
        out = rb.null_field({"a": 1}, "a")
        self.assertIsNone(out["a"])

    def test_empty_field_string_to_blank(self) -> None:
        out = rb.empty_field({"a": "foo"}, "a")
        self.assertEqual(out["a"], "")

    def test_empty_field_number_to_zero(self) -> None:
        out = rb.empty_field({"a": 5.5}, "a")
        self.assertEqual(out["a"], 0)

    def test_extreme_value_injects_big_negative(self) -> None:
        out = rb.extreme_value({"a": 10}, "a")
        self.assertLess(out["a"], -1e6)

    def test_typo_field_swaps_first_two(self) -> None:
        out = rb.typo_field({"a": "audio"}, "a")
        self.assertEqual(out["a"], "uadio")

    def test_case_swap_uppercases(self) -> None:
        out = rb.case_swap({"a": "audio"}, "a")
        self.assertEqual(out["a"], "AUDIO")

    def test_wrong_type_int_to_str(self) -> None:
        out = rb.wrong_type({"a": 5}, "a")
        self.assertIsInstance(out["a"], str)


class TestFragileRule(unittest.TestCase):
    def test_fragile_crashes_on_perturbations(self) -> None:
        report = rb.test_rule(
            _fragile_rule,
            baseline={"niche": "audio", "price": 10},
        )
        self.assertGreater(len(report.crashes), 0)
        self.assertLess(report.score, 1.0)


class TestRobustRule(unittest.TestCase):
    def test_robust_rule_never_crashes(self) -> None:
        report = rb.test_rule(
            _robust_rule,
            baseline={"niche": "audio", "price": 10},
        )
        # The robust rule should never raise, and should not change
        # output type — swings are allowed since the rule legitimately
        # depends on the inputs.
        self.assertEqual(len(report.crashes), 0)
        self.assertEqual(len(report.type_violations), 0)


class TestBaselineCrash(unittest.TestCase):
    def test_baseline_crash_returns_single_crash(self) -> None:
        def always_crash(payload):
            raise RuntimeError("boom")
        report = rb.test_rule(always_crash, baseline={"a": 1})
        self.assertEqual(len(report.crashes), 1)
        self.assertEqual(report.crashes[0].field, "*")
        self.assertEqual(report.total, 1)


class TestTypeViolation(unittest.TestCase):
    def test_type_violation_caught(self) -> None:
        def flaky(payload):
            if payload.get("a") is None:
                return "string instead of dict"
            return {"score": 1}
        report = rb.test_rule(flaky, baseline={"a": 1})
        self.assertGreater(len(report.type_violations), 0)


class TestSwing(unittest.TestCase):
    def test_large_output_swing_flagged(self) -> None:
        def sensitive(payload):
            return {"score": payload.get("x", 0) * 1000}
        report = rb.test_rule(
            sensitive,
            baseline={"x": 1},
            swing_threshold=0.3,
        )
        self.assertGreater(len(report.swings), 0)


class TestScore(unittest.TestCase):
    def test_all_ok_gives_score_1(self) -> None:
        def constant(payload):
            return {"score": 1.0}
        report = rb.test_rule(
            constant,
            baseline={"niche": "audio", "price": 10},
        )
        self.assertAlmostEqual(report.score, 1.0)


class TestSweep(unittest.TestCase):
    def test_sweep_runs_per_baseline(self) -> None:
        reports = rb.sweep(
            _robust_rule,
            baselines=[
                {"niche": "audio", "price": 10},
                {"niche": "fashion", "price": 20},
            ],
        )
        self.assertEqual(len(reports), 2)


if __name__ == "__main__":
    unittest.main()
