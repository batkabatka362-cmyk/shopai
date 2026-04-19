"""Meta router tests."""
from __future__ import annotations

import unittest

from core.brain import meta_router as mr


class TestProvider(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            mr.Provider(name="", capabilities=("x",))

    def test_no_capabilities_raises(self) -> None:
        with self.assertRaises(ValueError):
            mr.Provider(name="p", capabilities=())

    def test_negative_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            mr.Provider(name="p", capabilities=("x",), cost=-1)

    def test_negative_latency_raises(self) -> None:
        with self.assertRaises(ValueError):
            mr.Provider(
                name="p", capabilities=("x",), latency_ms=-1,
            )

    def test_competence_default_mid(self) -> None:
        p = mr.Provider(name="p", capabilities=("x",))
        self.assertEqual(p.competence_for("x"), 0.5)

    def test_competence_raise_handled(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        p = mr.Provider(
            name="p", capabilities=("x",), competence_fn=boom,
        )
        self.assertEqual(p.competence_for("x"), 0.5)

    def test_competence_clamped(self) -> None:
        p = mr.Provider(
            name="p", capabilities=("x",),
            competence_fn=lambda c: 5.0,
        )
        self.assertEqual(p.competence_for("x"), 1.0)


class TestRegister(unittest.TestCase):
    def test_duplicate_rejected(self) -> None:
        r = mr.MetaRouter()
        p = mr.Provider(name="p", capabilities=("x",))
        r.register(p)
        with self.assertRaises(ValueError):
            r.register(p)

    def test_overwrite_allowed(self) -> None:
        r = mr.MetaRouter()
        r.register(mr.Provider(name="p", capabilities=("x",), cost=1))
        r.register(
            mr.Provider(name="p", capabilities=("x",), cost=5),
            overwrite=True,
        )
        self.assertEqual(r.providers()[0].cost, 5)

    def test_unregister(self) -> None:
        r = mr.MetaRouter()
        r.register(mr.Provider(name="p", capabilities=("x",)))
        self.assertTrue(r.unregister("p"))
        self.assertFalse(r.unregister("p"))


class TestRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.r = mr.MetaRouter()
        self.r.register(mr.Provider(
            name="cheap",
            capabilities=("decision.kill_ad",),
            cost=1.0, latency_ms=10,
            competence_fn=lambda c: 0.6,
        ))
        self.r.register(mr.Provider(
            name="expert",
            capabilities=("decision.kill_ad",),
            cost=5.0, latency_ms=100,
            competence_fn=lambda c: 0.95,
        ))
        self.r.register(mr.Provider(
            name="other_cap",
            capabilities=("retrieval.cases",),
            cost=1.0,
        ))

    def test_blank_capability_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.route("")

    def test_bad_top_k_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.route("decision.kill_ad", top_k=0)

    def test_picks_best_cost_competence(self) -> None:
        decisions = self.r.route("decision.kill_ad", top_k=2)
        # cheap: 0.6/1 = 0.6; expert: 0.95/5 = 0.19 → cheap wins
        self.assertEqual(decisions[0].provider, "cheap")

    def test_budget_excludes_over_cost(self) -> None:
        decisions = self.r.route(
            "decision.kill_ad", budget=2.0, top_k=5,
        )
        names = [d.provider for d in decisions]
        self.assertIn("cheap", names)
        self.assertNotIn("expert", names)

    def test_deadline_excludes_slow(self) -> None:
        decisions = self.r.route(
            "decision.kill_ad", deadline_ms=50, top_k=5,
        )
        names = [d.provider for d in decisions]
        self.assertIn("cheap", names)
        self.assertNotIn("expert", names)

    def test_no_supporters_returns_empty(self) -> None:
        self.assertEqual(
            self.r.route("nobody.knows.this"), [],
        )

    def test_surface_ineligible_when_nothing_routes(self) -> None:
        # Both providers fail the strict budget → surface them anyway
        # so caller sees why nothing succeeded.
        decisions = self.r.route(
            "decision.kill_ad", budget=0.5, top_k=5,
        )
        # Best-effort: both candidates reported with score 0
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(d.score == 0.0 for d in decisions))


class TestBest(unittest.TestCase):
    def test_best_picks_top(self) -> None:
        r = mr.MetaRouter()
        r.register(mr.Provider(
            name="a", capabilities=("x",),
            cost=1.0, competence_fn=lambda c: 0.9,
        ))
        r.register(mr.Provider(
            name="b", capabilities=("x",),
            cost=1.0, competence_fn=lambda c: 0.2,
        ))
        self.assertEqual(r.best("x").provider, "a")

    def test_best_none_when_empty(self) -> None:
        r = mr.MetaRouter()
        self.assertIsNone(r.best("x"))


class TestStats(unittest.TestCase):
    def test_stats_lists_capabilities(self) -> None:
        r = mr.MetaRouter()
        r.register(mr.Provider(name="a", capabilities=("x", "y")))
        r.register(mr.Provider(name="b", capabilities=("y", "z")))
        s = r.stats()
        self.assertEqual(s["providers"], 2)
        self.assertEqual(set(s["capabilities"]), {"x", "y", "z"})


class TestDict(unittest.TestCase):
    def test_provider_serialises(self) -> None:
        p = mr.Provider(
            name="p", capabilities=("x", "y"),
            cost=2.0, latency_ms=50, description="demo",
        )
        d = p.as_dict()
        self.assertEqual(d["name"], "p")
        self.assertEqual(d["capabilities"], ["x", "y"])

    def test_route_decision_serialises(self) -> None:
        r = mr.MetaRouter()
        r.register(mr.Provider(
            name="a", capabilities=("x",),
            competence_fn=lambda c: 0.8,
        ))
        d = r.best("x").as_dict()
        self.assertIn("score", d)
        self.assertIn("competence", d)


if __name__ == "__main__":
    unittest.main()
