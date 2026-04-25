"""Outcome router tests."""
from __future__ import annotations

import unittest

from core.brain import outcome_router as orut


class TestSubscribe(unittest.TestCase):
    def setUp(self) -> None:
        self.r = orut.OutcomeRouter()
        # Clear default subscribers for a clean slate
        self.r.clear()

    def test_subscribe_and_emit(self) -> None:
        received: list = []
        self.r.subscribe("order", lambda o: received.append(o),
                         name="collector")
        rep = self.r.emit(orut.Outcome(kind="order", sign=1.0))
        self.assertIn("collector", rep.delivered)
        self.assertEqual(len(received), 1)

    def test_emit_without_subscribers_skips(self) -> None:
        rep = self.r.emit(orut.Outcome(kind="never_seen"))
        self.assertEqual(rep.delivered, [])
        self.assertTrue(any("no subscribers" in s for s in rep.skipped))

    def test_unsubscribe(self) -> None:
        self.r.subscribe("k", lambda o: None, name="x")
        self.assertTrue(self.r.unsubscribe("k", "x"))
        self.assertFalse(self.r.unsubscribe("k", "x"))

    def test_subscribers_listing(self) -> None:
        self.r.subscribe("k", lambda o: None, name="a")
        self.r.subscribe("k", lambda o: None, name="b")
        self.assertEqual(set(self.r.subscribers("k")), {"a", "b"})


class TestErrorIsolation(unittest.TestCase):
    def test_one_handler_crashing_doesnt_block_others(self) -> None:
        r = orut.OutcomeRouter()
        r.clear()
        delivered: list[str] = []
        def good(o):
            delivered.append("good")
        def bad(o):
            raise ValueError("boom")
        r.subscribe("x", bad, name="bad")
        r.subscribe("x", good, name="good")
        rep = r.emit(orut.Outcome(kind="x"))
        self.assertIn("good", rep.delivered)
        self.assertEqual(len(rep.errors), 1)
        self.assertEqual(rep.errors[0][0], "bad")


class TestDefaultSubscribers(unittest.TestCase):
    def test_default_order_has_multiple_subscribers(self) -> None:
        r = orut.OutcomeRouter()
        subs = r.subscribers("order")
        # Expect at least reward, trust, epistemic, habit, world,
        # policy handlers present.
        self.assertGreaterEqual(len(subs), 5)

    def test_default_hypothesis_resolve_wires_resolver(self) -> None:
        r = orut.OutcomeRouter()
        self.assertIn(
            "hypothesis", r.subscribers("hypothesis_resolved"),
        )


class TestOutcomeFields(unittest.TestCase):
    def test_as_dict_roundtrip(self) -> None:
        o = orut.Outcome(
            kind="order",
            features={"niche": "audio"},
            source="shopify_api",
            sign=1.0,
            success=True,
            value=100.0,
            kpi="revenue",
            action="scale",
            policy_name="audio_scale",
        )
        d = o.as_dict()
        self.assertEqual(d["kind"], "order")
        self.assertEqual(d["features"]["niche"], "audio")


class TestSingleton(unittest.TestCase):
    def test_router_returns_same_instance(self) -> None:
        a = orut.router()
        b = orut.router()
        self.assertIs(a, b)


if __name__ == "__main__":
    unittest.main()
