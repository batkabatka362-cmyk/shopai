"""Test suite for engine system — import, structure, execution."""
import unittest
import random
from engines.registry import get_engine, list_engines, engine_count, is_registered, clear_cache
from engines.base.engine_types import EngineInput, EngineStatus


class TestEngineRegistry(unittest.TestCase):
    def test_engine_count(self):
        self.assertGreaterEqual(engine_count(), 2270)

    def test_list_engines_sorted(self):
        engines = list_engines()
        self.assertEqual(engines, sorted(engines))

    def test_is_registered(self):
        self.assertTrue(is_registered("product_selection"))
        self.assertTrue(is_registered("pricing"))
        self.assertFalse(is_registered("nonexistent_engine_xyz"))

    def test_get_engine_caches(self):
        clear_cache()
        e1 = get_engine("product_selection")
        e2 = get_engine("product_selection")
        self.assertIs(e1, e2)

    def test_get_unknown_engine_raises(self):
        with self.assertRaises(KeyError):
            get_engine("totally_nonexistent_engine_12345")

    def test_clear_cache(self):
        get_engine("pricing")
        clear_cache()
        # Should still work after clear
        e = get_engine("pricing")
        self.assertEqual(e.engine_name, "pricing")


class TestEngineImport(unittest.TestCase):
    def test_import_all_engines(self):
        """All registered engines must import without error."""
        import importlib
        errors = []
        for name in list_engines():
            try:
                importlib.import_module(f"engines.{name}.engine")
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self.assertEqual(errors, [], f"Failed imports: {errors[:5]}")


class TestEngineStructure(unittest.TestCase):
    def test_engine_has_required_attrs(self):
        """Every engine must have engine_name, required_input_fields, required_output_fields."""
        sample = random.sample(list_engines(), min(50, engine_count()))
        for name in sample:
            e = get_engine(name)
            self.assertTrue(hasattr(e, "engine_name"), f"{name} missing engine_name")
            self.assertTrue(hasattr(e, "required_input_fields"), f"{name} missing required_input_fields")
            self.assertTrue(hasattr(e, "required_output_fields"), f"{name} missing required_output_fields")

    def test_engine_has_define_steps(self):
        sample = random.sample(list_engines(), min(50, engine_count()))
        for name in sample:
            e = get_engine(name)
            self.assertTrue(hasattr(e, "define_steps"), f"{name} missing define_steps")
            self.assertTrue(callable(e.define_steps))

    def test_engine_has_4_steps(self):
        e = get_engine("product_selection")
        steps = e.flow.get_steps()
        self.assertEqual(len(steps), 4)
        names = [s.name for s in steps]
        self.assertEqual(names, ["analyze", "execute", "enhance", "validate"])


class TestEngineExecution(unittest.TestCase):
    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_product_selection_runs(self):
        e = get_engine("product_selection")
        inp = EngineInput(task_id="test_ps", engine_name="product_selection", data={
            "products": [{"name": "Test", "price": 30, "cost": 8}],
            "criteria": {"min_margin": 30},
        })
        out = e.run(inp)
        self.assertEqual(out.status, EngineStatus.COMPLETED)
        self.assertIn("scored_products", out.result)
        self.assertIn("selected_products", out.result)

    def test_pricing_runs(self):
        e = get_engine("pricing")
        inp = EngineInput(task_id="test_pr", engine_name="pricing", data={
            "products": [{"name": "X", "price": 30, "cost": 8}],
        })
        out = e.run(inp)
        self.assertEqual(out.status, EngineStatus.COMPLETED)
        self.assertIn("price_analysis", out.result)
        self.assertIn("pricing_recommendations", out.result)

    def test_customer_segmentation_runs(self):
        e = get_engine("customer_segmentation")
        inp = EngineInput(task_id="test_cs", engine_name="customer_segmentation", data={
            "customer_data": [{"name": "A", "orders": 5, "total_spent": 200, "days_since_last_order": 10}],
            "segmentation_criteria": {},
        })
        out = e.run(inp)
        self.assertEqual(out.status, EngineStatus.COMPLETED)
        self.assertIn("customer_analysis", out.result)
        self.assertIn("rfm_segments", out.result)

    def test_engine_never_crashes(self):
        """Engine should return FAILED status, not raise exception."""
        e = get_engine("product_selection")
        inp = EngineInput(task_id="test_crash", engine_name="product_selection", data={})
        out = e.run(inp)
        # Should not crash — either completed or failed
        self.assertIn(out.status, [EngineStatus.COMPLETED, EngineStatus.FAILED])

    def test_engine_output_has_intelligence(self):
        e = get_engine("pricing")
        inp = EngineInput(task_id="test_intel", engine_name="pricing", data={
            "products": [{"name": "X", "price": 30, "cost": 8}],
        })
        out = e.run(inp)
        self.assertIn("_intelligence", out.result)
        intel = out.result["_intelligence"]
        self.assertIn("confidence", intel)
        self.assertIn("next_steps", intel)

    def test_engine_output_has_timing(self):
        e = get_engine("pricing")
        inp = EngineInput(task_id="test_time", engine_name="pricing", data={
            "products": [{"name": "X", "price": 30, "cost": 8}],
        })
        out = e.run(inp)
        self.assertIn("_timing", out.result)
        self.assertIn("total_ms", out.result["_timing"])

    def test_mass_engine_execution(self):
        """100 random engines must all complete."""
        sample = random.sample(list_engines(), 100)
        for name in sample:
            e = get_engine(name)
            data = {f: {} for f in e.required_input_fields}
            inp = EngineInput(task_id=f"mass_{name}", engine_name=name, data=data)
            out = e.run(inp)
            self.assertEqual(out.status, EngineStatus.COMPLETED, f"{name} failed: {out.error}")


if __name__ == "__main__":
    unittest.main()
