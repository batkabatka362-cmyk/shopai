"""Brain module catalog tests (audit batch 4).

The brain tree has ~225 modules with mixed wire-up states.
The catalog is an honest label layer: active / experimental /
archived / unknown. These tests lock the API so future
categorisation passes stay consistent.
"""
from __future__ import annotations

import unittest

from core.brain.module_catalog import (
    ModuleStatus,
    catalog_summary,
    declare_module,
    module_status,
    modules_by_category,
)


class TestModuleCatalog(unittest.TestCase):
    def test_default_unknown(self):
        s = module_status("definitely_not_a_real_module_xyz")
        self.assertEqual(s.category, "unknown")
        self.assertEqual(s.reason, "")

    def test_declared_modules_present(self):
        # From the bootstrap declarations in module_catalog.py
        for name in (
            "ab_bandit", "abstraction_ladder", "anomaly_triage",
            "model_coordinator", "analogy_mapper",
        ):
            s = module_status(name)
            self.assertEqual(
                s.category, "experimental",
                msg=f"{name} should be experimental",
            )
            self.assertTrue(
                s.reason,
                msg=f"{name} needs a reason",
            )

    def test_active_modules_declared(self):
        """At least one module must be labelled ``active`` —
        otherwise the catalog would paint everything as parked
        which is dishonest."""
        actives = modules_by_category("active")
        self.assertGreaterEqual(len(actives), 3)
        names = {s.name for s in actives}
        self.assertIn("structured_decision", names)

    def test_summary_shape(self):
        s = catalog_summary()
        self.assertIn("total_declared", s)
        self.assertIn("by_category", s)
        self.assertIn("entries", s)
        for c in (
            "active", "experimental", "archived", "unknown",
        ):
            self.assertIn(c, s["by_category"])
        # Entries sorted by (category, name)
        entries = s["entries"]
        pairs = [
            (e["category"], e["name"]) for e in entries
        ]
        self.assertEqual(pairs, sorted(pairs))

    def test_invalid_category_rejected(self):
        with self.assertRaises(ValueError):
            declare_module("x", category="bogus")

    def test_invalid_category_for_by_category(self):
        with self.assertRaises(ValueError):
            modules_by_category("bogus")

    def test_name_required(self):
        with self.assertRaises(ValueError):
            declare_module("", category="experimental")

    def test_re_declare_overwrites(self):
        # Pick an unused name so the test doesn't pollute other
        # suites' expectations.
        declare_module(
            "__test_temp_mod__",
            category="experimental",
            reason="first",
        )
        declare_module(
            "__test_temp_mod__",
            category="archived",
            reason="second",
        )
        s = module_status("__test_temp_mod__")
        self.assertEqual(s.category, "archived")
        self.assertEqual(s.reason, "second")

    def test_module_status_returns_module_status(self):
        s = module_status("structured_decision")
        self.assertIsInstance(s, ModuleStatus)


class TestCatalogScale(unittest.TestCase):
    """Catalog expansion tracker — CLAUDE.md §8 tracker
    claims ≥25 declarations. This test asserts the floor so
    future accidental deletions are caught."""

    def test_at_least_25_declarations(self):
        s = catalog_summary()
        self.assertGreaterEqual(
            s["total_declared"], 25,
            msg=(
                f"Catalog shrunk to "
                f"{s['total_declared']} — check if "
                f"bootstrap declarations got removed."
            ),
        )

    def test_at_least_5_active_declarations(self):
        actives = modules_by_category("active")
        self.assertGreaterEqual(len(actives), 5)
        # Spot-check: decision_brain + compute_budget must be
        # active (they're in the hot path)
        names = {s.name for s in actives}
        self.assertIn("decision_brain", names)
        self.assertIn("compute_budget", names)

    def test_major_orphans_declared(self):
        """Previously-flagged orphans (from the audit) now
        have an explicit category."""
        for name in (
            "causal_discovery", "churn_predictor",
            "drift_detector", "counterfactual",
            "economic_simulator", "forecaster",
        ):
            s = module_status(name)
            self.assertNotEqual(
                s.category, "unknown",
                msg=f"{name} must be declared",
            )


class TestMCPBrainModuleCatalog(unittest.TestCase):
    def test_tool_registered_read_only(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("brain_module_catalog", specs)
        self.assertFalse(specs["brain_module_catalog"].write)

    def test_handler_returns_summary_shape(self):
        from mcp_server.tools import (
            _brain_module_catalog_handler,
        )
        out = _brain_module_catalog_handler({})
        self.assertIn("total_declared", out)
        self.assertIn("by_category", out)
        self.assertIn("entries", out)


if __name__ == "__main__":
    unittest.main()
