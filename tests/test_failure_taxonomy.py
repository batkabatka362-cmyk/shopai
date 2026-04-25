"""Failure taxonomy tests."""
from __future__ import annotations

import unittest

from core.brain import failure_taxonomy as ft


class TestClassify(unittest.TestCase):
    def setUp(self) -> None:
        self.t = ft.FailureTaxonomy()

    def test_capacity_429(self) -> None:
        r = self.t.classify(status_code=429, message="")
        self.assertEqual(r.category, "capacity")

    def test_capacity_rate_limit_message(self) -> None:
        r = self.t.classify(
            message="Rate limit exceeded for GraphQL",
        )
        self.assertEqual(r.category, "capacity")

    def test_timeout_exception(self) -> None:
        r = self.t.classify(
            message="",
            exception_type="TimeoutError",
        )
        self.assertEqual(r.category, "timeout")

    def test_timeout_504(self) -> None:
        r = self.t.classify(status_code=504)
        self.assertEqual(r.category, "timeout")

    def test_auth_401(self) -> None:
        r = self.t.classify(
            status_code=401, message="Unauthorized",
        )
        self.assertEqual(r.category, "auth")

    def test_auth_message(self) -> None:
        r = self.t.classify(
            message="invalid token",
        )
        self.assertEqual(r.category, "auth")

    def test_validation(self) -> None:
        r = self.t.classify(status_code=400)
        self.assertEqual(r.category, "validation")

    def test_api_500(self) -> None:
        r = self.t.classify(status_code=500)
        self.assertEqual(r.category, "api")

    def test_external(self) -> None:
        r = self.t.classify(
            message="connection refused to downstream",
        )
        self.assertEqual(r.category, "external")

    def test_logic(self) -> None:
        r = self.t.classify(
            exception_type="KeyError",
        )
        self.assertEqual(r.category, "logic")

    def test_unknown(self) -> None:
        r = self.t.classify(
            message="total jibberish xyzzy",
        )
        self.assertEqual(r.category, "unknown")


class TestRegistry(unittest.TestCase):
    def test_register(self) -> None:
        rule = ft.ClassificationRule(
            id="custom", category="external",
            message_patterns=("pipeline_x_down",),
            priority=1,
        )
        t = ft.FailureTaxonomy()
        t.register_rule(rule)
        r = t.classify(message="pipeline_x_down")
        self.assertEqual(r.rule_id, "custom")

    def test_unregister(self) -> None:
        t = ft.FailureTaxonomy()
        self.assertTrue(t.unregister_rule("r_capacity"))
        # 429 should now fall through to unknown
        r = t.classify(status_code=429)
        self.assertEqual(r.category, "unknown")


class TestQueries(unittest.TestCase):
    def test_counts(self) -> None:
        t = ft.FailureTaxonomy()
        t.classify(status_code=429)
        t.classify(status_code=500)
        counts = t.counts()
        self.assertEqual(counts["capacity"], 1)
        self.assertEqual(counts["api"], 1)

    def test_dominant(self) -> None:
        t = ft.FailureTaxonomy()
        for _ in range(5):
            t.classify(status_code=429)
        t.classify(status_code=500)
        self.assertEqual(t.dominant_category(), "capacity")

    def test_dominant_empty(self) -> None:
        t = ft.FailureTaxonomy()
        self.assertIsNone(t.dominant_category())

    def test_recent(self) -> None:
        t = ft.FailureTaxonomy()
        for _ in range(3):
            t.classify(status_code=429)
        self.assertEqual(len(t.recent(limit=2)), 2)

    def test_stats(self) -> None:
        t = ft.FailureTaxonomy()
        t.classify(status_code=429)
        s = t.stats()
        self.assertEqual(s["total"], 1)
        self.assertIn("capacity", s["by_category"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        t = ft.FailureTaxonomy()
        t.classify(status_code=429)
        self.assertEqual(t.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        t = ft.FailureTaxonomy()
        r = t.classify(status_code=429)
        d = r.as_dict()
        self.assertEqual(d["category"], "capacity")


if __name__ == "__main__":
    unittest.main()
