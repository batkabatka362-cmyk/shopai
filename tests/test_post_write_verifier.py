"""Tests for execution.verify.post_write_verifier — Track 5."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from execution.verify.post_write_verifier import (
    DriftReport,
    VerifyConfig,
    _dig,
    _equal,
    verify_write,
)


class TestEqual(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(_equal(1, 1, tolerance=None))
        self.assertFalse(_equal(1, 2, tolerance=None))

    def test_float_tolerance(self):
        self.assertTrue(
            _equal(10.00, 10.009, tolerance=0.02),
        )
        self.assertFalse(
            _equal(10.00, 10.05, tolerance=0.02),
        )

    def test_string_prefix(self):
        self.assertTrue(
            _equal("abc", "abcdef", tolerance="prefix"),
        )
        self.assertFalse(
            _equal("x", "abcdef", tolerance="prefix"),
        )

    def test_string_contains(self):
        self.assertTrue(
            _equal("mid", "prefixmidsuffix",
                   tolerance="contains"),
        )

    def test_string_case_insensitive(self):
        self.assertTrue(
            _equal("HELLO", "hello",
                   tolerance="case_insensitive"),
        )

    def test_string_numeric_cross_type(self):
        self.assertTrue(
            _equal(29.99, "29.99", tolerance=None),
        )
        self.assertTrue(
            _equal("15", 15, tolerance=None),
        )

    def test_bad_tolerance_float_rejects(self):
        self.assertFalse(
            _equal("abc", "xyz", tolerance=0.1),
        )


class TestDig(unittest.TestCase):
    def test_dict_path(self):
        found, val = _dig(
            {"a": {"b": 42}}, "a.b",
        )
        self.assertTrue(found)
        self.assertEqual(val, 42)

    def test_missing_segment(self):
        found, val = _dig(
            {"a": {"b": 42}}, "a.c",
        )
        self.assertFalse(found)
        self.assertIsNone(val)

    def test_object_attr(self):
        obj = MagicMock()
        obj.status = "active"
        found, val = _dig(obj, "status")
        self.assertTrue(found)
        self.assertEqual(val, "active")


class TestConfigValidation(unittest.TestCase):
    def test_empty_fields_raises(self):
        with self.assertRaises(ValueError):
            VerifyConfig(fields=())

    def test_verify_write_needs_fields_or_config(self):
        with self.assertRaises(ValueError):
            verify_write(
                read_fn=lambda: {},
                expected={},
            )


class TestVerify(unittest.TestCase):
    def test_no_drift_when_match(self):
        r = verify_write(
            read_fn=lambda: {
                "price": 29.99, "status": "active",
            },
            expected={
                "price": 29.99, "status": "active",
            },
            fields=("price", "status"),
        )
        self.assertFalse(r.drift)
        self.assertEqual(r.field_diffs, ())

    def test_drift_on_mismatch(self):
        r = verify_write(
            read_fn=lambda: {
                "price": 25.00, "status": "draft",
            },
            expected={
                "price": 29.99, "status": "active",
            },
            fields=("price", "status"),
        )
        self.assertTrue(r.drift)
        self.assertEqual(len(r.field_diffs), 2)

    def test_tolerance_absorbs_price_rounding(self):
        r = verify_write(
            read_fn=lambda: {"price": "29.98"},
            expected={"price": 29.99},
            fields=("price",),
            tolerance={"price": 0.05},
        )
        self.assertFalse(r.drift)

    def test_allow_missing_field(self):
        r = verify_write(
            read_fn=lambda: {"status": "active"},
            expected={
                "status": "active", "handle": "foo",
            },
            fields=("status", "handle"),
            allow_missing=("handle",),
        )
        self.assertFalse(r.drift)

    def test_missing_without_allow_is_drift(self):
        r = verify_write(
            read_fn=lambda: {"status": "active"},
            expected={
                "status": "active", "handle": "foo",
            },
            fields=("status", "handle"),
        )
        self.assertTrue(r.drift)
        self.assertEqual(
            r.field_diffs[0]["reason"], "missing",
        )

    def test_read_fn_exception_marks_drift(self):
        def boom():
            raise RuntimeError("Shopify 500")

        r = verify_write(
            read_fn=boom,
            expected={"price": 1},
            fields=("price",),
        )
        self.assertTrue(r.drift)
        self.assertFalse(r.read_ok)
        self.assertIn("Shopify 500", r.error)

    def test_nested_field_path(self):
        r = verify_write(
            read_fn=lambda: {
                "product": {"title": "Foo"},
            },
            expected={"product.title": "Foo"},
            fields=("product.title",),
        )
        self.assertFalse(r.drift)

    def test_object_read_supported(self):
        obj = MagicMock()
        obj.price = 10.0
        obj.status = "active"
        r = verify_write(
            read_fn=lambda: obj,
            expected={
                "price": 10.0, "status": "active",
            },
            fields=("price", "status"),
        )
        self.assertFalse(r.drift)

    def test_config_object_form(self):
        cfg = VerifyConfig(
            fields=("price",),
            tolerance={"price": 0.1},
            allow_missing=(),
        )
        r = verify_write(
            read_fn=lambda: {"price": 10.05},
            expected={"price": 10.0},
            config=cfg,
        )
        self.assertFalse(r.drift)

    def test_report_as_dict(self):
        r = verify_write(
            read_fn=lambda: {"price": 1},
            expected={"price": 2},
            fields=("price",),
        )
        d = r.as_dict()
        self.assertTrue(d["drift"])
        self.assertEqual(len(d["field_diffs"]), 1)


if __name__ == "__main__":
    unittest.main()
