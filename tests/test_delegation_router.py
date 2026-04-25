"""Delegation router tests."""
from __future__ import annotations

import unittest

from core.brain import delegation_router as dr


class TestRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.r = dr.DelegationRouter()

    def test_high_stakes_to_owner(self) -> None:
        task = dr.Task(
            kind="suspend_store",
            stakes=0.9, novelty=0.2,
            capability_name="suspend",
            urgency=1,
        )
        route = self.r.route(task)
        self.assertEqual(route.target, "owner")

    def test_novel_to_llm(self) -> None:
        task = dr.Task(
            kind="write_copy",
            stakes=0.5, novelty=0.8,
            capability_name="copy",
            urgency=1,
        )
        route = self.r.route(task)
        self.assertEqual(route.target, "llm")

    def test_urgent_low_to_engine(self) -> None:
        task = dr.Task(
            kind="adjust_budget",
            stakes=0.2, novelty=0.1,
            capability_name="budget",
            urgency=3,
        )
        route = self.r.route(task)
        self.assertEqual(route.target, "engine")

    def test_bad_stakes_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.route(dr.Task(
                kind="k", stakes=1.5, novelty=0.0,
                capability_name="c", urgency=0,
            ))

    def test_bad_novelty_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.route(dr.Task(
                kind="k", stakes=0.0, novelty=2.0,
                capability_name="c", urgency=0,
            ))

    def test_bad_urgency_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.route(dr.Task(
                kind="k", stakes=0.0, novelty=0.0,
                capability_name="c", urgency=-1,
            ))


class TestCapabilityFallback(unittest.TestCase):
    def test_missing_capability_skips(self) -> None:
        r = dr.DelegationRouter(
            capability_check=lambda name: False,
        )
        task = dr.Task(
            kind="k", stakes=0.3, novelty=0.1,
            capability_name="missing",
            urgency=0,
        )
        route = r.route(task)
        self.assertEqual(route.target, "skip")

    def test_available_capability_engine(self) -> None:
        r = dr.DelegationRouter(
            capability_check=lambda name: True,
        )
        task = dr.Task(
            kind="k", stakes=0.3, novelty=0.1,
            capability_name="c", urgency=0,
        )
        route = r.route(task)
        self.assertEqual(route.target, "engine")


class TestCustomRule(unittest.TestCase):
    def test_register_and_match(self) -> None:
        def matches(task):
            return task.kind == "always_skip"

        rule = dr.RoutingRule(
            id="custom_skip",
            priority=1,
            matches=matches,
            target="skip",
            reason="custom route",
            confidence=0.9,
        )
        r = dr.DelegationRouter()
        r.register_rule(rule)
        task = dr.Task(
            kind="always_skip",
            stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        )
        route = r.route(task)
        self.assertEqual(route.target, "skip")

    def test_unregister(self) -> None:
        r = dr.DelegationRouter()
        self.assertTrue(
            r.unregister_rule("safety_to_owner"),
        )
        # Now high stakes no longer auto-routes to owner
        route = r.route(dr.Task(
            kind="k", stakes=0.9, novelty=0.2,
            capability_name="c", urgency=0,
        ))
        self.assertNotEqual(route.target, "owner")


class TestFailingRule(unittest.TestCase):
    def test_raising_matches_is_skipped(self) -> None:
        def boom(_t):
            raise RuntimeError("bug")

        rule = dr.RoutingRule(
            id="boom", priority=1,
            matches=boom, target="skip",
            reason="bad",
        )
        r = dr.DelegationRouter(rules=[rule])
        task = dr.Task(
            kind="k", stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        )
        # Router should fall back to default
        route = r.route(task)
        self.assertEqual(route.target, "engine")


class TestQueries(unittest.TestCase):
    def test_recent(self) -> None:
        r = dr.DelegationRouter()
        for _ in range(3):
            r.route(dr.Task(
                kind="k", stakes=0.1, novelty=0.1,
                capability_name="c", urgency=0,
            ))
        self.assertEqual(len(r.recent(limit=2)), 2)

    def test_stats(self) -> None:
        r = dr.DelegationRouter()
        r.route(dr.Task(
            kind="k", stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        ))
        s = r.stats()
        self.assertIn("engine", s["by_target"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        r = dr.DelegationRouter()
        r.route(dr.Task(
            kind="k", stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        ))
        self.assertEqual(r.reset(), 1)


class TestDict(unittest.TestCase):
    def test_task_serialises(self) -> None:
        t = dr.Task(
            kind="k", stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        )
        d = t.as_dict()
        self.assertEqual(d["kind"], "k")

    def test_route_serialises(self) -> None:
        r = dr.DelegationRouter()
        route = r.route(dr.Task(
            kind="k", stakes=0.1, novelty=0.1,
            capability_name="c", urgency=0,
        ))
        d = route.as_dict()
        self.assertIn("target", d)


if __name__ == "__main__":
    unittest.main()
