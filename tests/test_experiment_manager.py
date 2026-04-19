"""Experiment manager tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import experiment_manager as em


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = em.ExperimentManager(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()


class TestRegister(TestSetup):
    def test_register_and_get(self) -> None:
        exp = self.m.register(
            "free_shipping", variants=["control", "free"],
        )
        self.assertEqual(exp.status, "running")
        self.assertIn("control", exp.variants)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.register("", variants=["a", "b"])

    def test_single_variant_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.register("e", variants=["only_one"])

    def test_duplicate_rejected(self) -> None:
        self.m.register("e", variants=["a", "b"])
        with self.assertRaises(ValueError):
            self.m.register("e", variants=["a", "b"])


class TestAllocation(TestSetup):
    def test_deterministic_allocation(self) -> None:
        self.m.register("e", variants=["a", "b"])
        first = self.m.allocate("e", "unit_1")
        second = self.m.allocate("e", "unit_1")
        self.assertEqual(first, second)

    def test_both_variants_used_over_many_units(self) -> None:
        self.m.register("e", variants=["a", "b"])
        seen = {
            self.m.allocate("e", f"unit_{i}")
            for i in range(200)
        }
        self.assertEqual(seen, {"a", "b"})

    def test_unknown_experiment_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.allocate("nobody", "u1")


class TestObserveAndStatus(TestSetup):
    def test_observe_stores_outcome(self) -> None:
        self.m.register("e", variants=["a", "b"])
        variant = self.m.observe("e", "unit_1", outcome=1.0)
        self.assertIn(variant, ("a", "b"))
        status = self.m.status("e")
        self.assertEqual(status.n_total, 1)

    def test_same_unit_dedupe(self) -> None:
        self.m.register("e", variants=["a", "b"])
        self.m.observe("e", "u1", outcome=1.0)
        self.m.observe("e", "u1", outcome=1.0)   # dup
        self.assertEqual(self.m.status("e").n_total, 1)

    def test_status_shape(self) -> None:
        self.m.register("e", variants=["a", "b"])
        for i in range(10):
            self.m.observe("e", f"u{i}", outcome=float(i))
        status = self.m.status("e")
        self.assertIn("a", status.per_variant)
        self.assertIn("b", status.per_variant)


class TestLeaderAndSignificance(TestSetup):
    def test_clear_winner_significant(self) -> None:
        self.m.register("e", variants=["control", "treatment"])
        # Force allocations via direct observe — controller hashes
        # unit ids so we feed many to get both groups full.
        # Use unit ids that we know land in each variant by checking
        # allocation first.
        a_units: list[str] = []
        b_units: list[str] = []
        for i in range(400):
            uid = f"u_{i}"
            v = self.m.allocate("e", uid)
            if v == "control" and len(a_units) < 150:
                a_units.append(uid)
            elif v == "treatment" and len(b_units) < 150:
                b_units.append(uid)
            if len(a_units) >= 150 and len(b_units) >= 150:
                break
        for uid in a_units:
            self.m.observe("e", uid, outcome=0.10)
        for uid in b_units:
            self.m.observe("e", uid, outcome=0.30)
        status = self.m.status("e")
        self.assertEqual(status.leader, "treatment")
        self.assertTrue(status.significant)

    def test_similar_variants_not_significant(self) -> None:
        self.m.register("e", variants=["control", "treatment"])
        import random
        random.seed(42)
        for i in range(200):
            uid = f"u_{i}"
            self.m.observe(
                "e", uid, outcome=random.uniform(0.0, 1.0),
            )
        status = self.m.status("e")
        # Noise-only: almost never significant at n=200
        self.assertFalse(status.significant)


class TestPromote(TestSetup):
    def test_promote_requires_min_samples(self) -> None:
        self.m.register("e", variants=["control", "treatment"])
        # Only 3 samples per variant — way below threshold
        for uid in ("u1", "u2", "u3"):
            self.m.observe("e", uid, outcome=5.0)
        fired = self.m.promote("e", min_samples_per_variant=100)
        self.assertFalse(fired)

    def test_promote_stops_running(self) -> None:
        self.m.register("e", variants=["control", "treatment"])
        # Fill both with strong separation
        for i in range(400):
            uid = f"u_{i}"
            v = self.m.allocate("e", uid)
            self.m.observe(
                "e", uid,
                outcome=0.3 if v == "treatment" else 0.0,
            )
        fired = self.m.promote("e", min_samples_per_variant=50)
        self.assertTrue(fired)
        exp = self.m.get("e")
        self.assertEqual(exp.status, "promoted")
        self.assertTrue(exp.promoted_variant)

    def test_promoted_allocate_returns_winner(self) -> None:
        self.m.register("e", variants=["control", "treatment"])
        for i in range(300):
            uid = f"u_{i}"
            v = self.m.allocate("e", uid)
            self.m.observe(
                "e", uid,
                outcome=0.3 if v == "treatment" else 0.0,
            )
        self.m.promote("e", min_samples_per_variant=50)
        # New unit now lands deterministically on the promoted variant
        self.assertEqual(
            self.m.allocate("e", "brand_new_unit"),
            self.m.get("e").promoted_variant,
        )


class TestStop(TestSetup):
    def test_stopped_experiment_allocates_first_variant(self) -> None:
        self.m.register("e", variants=["a", "b"])
        self.m.stop("e")
        self.assertEqual(self.m.allocate("e", "u1"), "a")

    def test_stopped_status_shown(self) -> None:
        self.m.register("e", variants=["a", "b"])
        self.m.stop("e")
        self.assertEqual(self.m.get("e").status, "stopped")


class TestStats(TestSetup):
    def test_stats_shape(self) -> None:
        self.m.register("e1", variants=["a", "b"])
        self.m.register("e2", variants=["a", "b"])
        self.m.stop("e2")
        s = self.m.stats()
        self.assertGreaterEqual(s["by_status"].get("running", 0), 1)
        self.assertGreaterEqual(s["by_status"].get("stopped", 0), 1)


class TestDict(TestSetup):
    def test_status_as_dict(self) -> None:
        self.m.register("e", variants=["a", "b"])
        self.m.observe("e", "u1", outcome=1.0)
        d = self.m.status("e").as_dict()
        self.assertIn("per_variant", d)
        self.assertIn("leader", d)


if __name__ == "__main__":
    unittest.main()
