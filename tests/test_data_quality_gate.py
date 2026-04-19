"""Data quality gate tests."""
from __future__ import annotations

import unittest

from core.system import data_quality_gate as dqg


class TestRequired(unittest.TestCase):
    def test_missing_field_fails(self) -> None:
        gate = dqg.DataQualityGate([dqg.required("currency")])
        r = gate.check({})
        self.assertEqual(r.status, "fail")
        self.assertEqual(r.issues[0].rule, "required")

    def test_present_passes(self) -> None:
        gate = dqg.DataQualityGate([dqg.required("currency")])
        r = gate.check({"currency": "USD"})
        self.assertEqual(r.status, "pass")

    def test_none_treated_as_missing(self) -> None:
        gate = dqg.DataQualityGate([dqg.required("x")])
        r = gate.check({"x": None})
        self.assertEqual(r.status, "fail")


class TestTypeCheck(unittest.TestCase):
    def test_correct_type_passes(self) -> None:
        gate = dqg.DataQualityGate([dqg.type_check("price", float)])
        r = gate.check({"price": 19.99})
        self.assertEqual(r.status, "pass")

    def test_coerce_int_to_float(self) -> None:
        gate = dqg.DataQualityGate([dqg.type_check("price", float)])
        r = gate.check({"price": "29.99"})
        self.assertEqual(r.status, "warn")
        self.assertIsInstance(r.cleaned_payload["price"], float)

    def test_uncoercible_fails(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.type_check("price", int, coerce=True),
        ])
        r = gate.check({"price": "not_a_number"})
        self.assertEqual(r.status, "fail")


class TestNumericRange(unittest.TestCase):
    def test_within_range(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.numeric_range("price", 0, 1000),
        ])
        r = gate.check({"price": 50})
        self.assertEqual(r.status, "pass")

    def test_out_of_range_clamped(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.numeric_range("price", 0, 100, clamp=True),
        ])
        r = gate.check({"price": 500})
        self.assertEqual(r.status, "warn")
        self.assertEqual(r.cleaned_payload["price"], 100)

    def test_non_numeric_fails(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.numeric_range("price", 0, 100),
        ])
        r = gate.check({"price": "n/a"})
        self.assertEqual(r.status, "warn")


class TestRegex(unittest.TestCase):
    def test_match_passes(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.regex("email", r"@"),
        ])
        r = gate.check({"email": "alice@example.com"})
        self.assertEqual(r.status, "pass")

    def test_no_match_fails(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.regex("email", r"@"),
        ])
        r = gate.check({"email": "no-at-sign"})
        self.assertEqual(r.status, "fail")

    def test_non_string_fails(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.regex("email", r"@"),
        ])
        r = gate.check({"email": 42})
        self.assertEqual(r.status, "fail")


class TestEnum(unittest.TestCase):
    def test_allowed_value(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.enum("currency", ["USD", "EUR", "GBP"]),
        ])
        r = gate.check({"currency": "USD"})
        self.assertEqual(r.status, "pass")

    def test_case_fix(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.enum("currency", ["USD", "EUR"]),
        ])
        r = gate.check({"currency": "usd"})
        self.assertEqual(r.status, "warn")
        self.assertEqual(r.cleaned_payload["currency"], "USD")

    def test_disallowed_fails(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.enum("currency", ["USD"]),
        ])
        r = gate.check({"currency": "JPY"})
        self.assertEqual(r.status, "fail")


class TestLength(unittest.TestCase):
    def test_too_short(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.length("name", min_len=3),
        ])
        r = gate.check({"name": "ab"})
        self.assertEqual(r.status, "warn")

    def test_too_long(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.length("name", max_len=5),
        ])
        r = gate.check({"name": "much too long"})
        self.assertEqual(r.status, "warn")

    def test_within_bounds(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.length("name", min_len=2, max_len=10),
        ])
        r = gate.check({"name": "alice"})
        self.assertEqual(r.status, "pass")


class TestCompound(unittest.TestCase):
    def test_multiple_rules_fire(self) -> None:
        gate = dqg.DataQualityGate([
            dqg.required("currency"),
            dqg.numeric_range("price", 0, 100),
            dqg.enum("tier", ["pro", "free"]),
        ])
        r = gate.check({"price": 500, "tier": "ENTERPRISE"})
        # Missing currency → fail; price clamped → warn; enum fail.
        self.assertEqual(r.status, "fail")
        rules = {i.rule for i in r.issues}
        self.assertIn("required", rules)
        self.assertIn("numeric_range", rules)

    def test_evaluator_crash_captured_as_fail(self) -> None:
        def boom_eval(v, payload):
            raise RuntimeError("bad rule")
        gate = dqg.DataQualityGate([dqg.Rule(
            name="boom", field="x", severity="warn",
            evaluator=boom_eval,
        )])
        r = gate.check({"x": 1})
        self.assertEqual(r.status, "fail")
        self.assertIn("evaluator crashed", r.issues[0].detail)


class TestAdd(unittest.TestCase):
    def test_add_individual_rule(self) -> None:
        gate = dqg.DataQualityGate()
        gate.add(dqg.required("x"))
        gate.add_many([dqg.required("y")])
        self.assertEqual(len(gate.rules()), 2)


if __name__ == "__main__":
    unittest.main()
