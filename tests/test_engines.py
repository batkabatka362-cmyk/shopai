"""Test suite for engine system — import, registry, execution.

Tests both flow.py (new pattern) and engine.py (legacy) engines.
"""
import unittest
import random
from engines.registry import get_engine, list_engines, engine_count, is_registered, clear_cache


class TestEngineRegistry(unittest.TestCase):
    def test_engine_count(self):
        self.assertGreaterEqual(engine_count(), 90)

    def test_list_engines_sorted(self):
        engines = list_engines()
        self.assertEqual(engines, sorted(engines))

    def test_is_registered(self):
        self.assertTrue(is_registered("product_selection"))
        self.assertTrue(is_registered("pricing"))
        self.assertTrue(is_registered("order_management"))
        self.assertTrue(is_registered("fraud_detection"))
        self.assertFalse(is_registered("nonexistent_engine_xyz"))

    def test_get_engine_caches(self):
        clear_cache()
        e1 = get_engine("product_selection")
        e2 = get_engine("product_selection")
        self.assertIs(e1, e2)

    def test_get_unknown_engine_returns_none(self):
        result = get_engine("totally_nonexistent_engine_12345")
        self.assertIsNone(result)

    def test_clear_cache(self):
        get_engine("pricing")
        clear_cache()
        e = get_engine("pricing")
        self.assertIsNotNone(e)
        # New pattern uses ENGINE_NAME class attribute
        self.assertEqual(e.ENGINE_NAME, "pricing")


class TestEngineImport(unittest.TestCase):
    def test_import_all_engines(self):
        """All registered engines must be importable."""
        errors = []
        for name in list_engines():
            e = get_engine(name)
            if e is None:
                errors.append(f"{name}: get_engine returned None")
        self.assertEqual(errors, [], f"Failed imports: {errors[:10]}")

    def test_all_engines_have_run(self):
        """Every engine must have a run() method."""
        sample = random.sample(list_engines(), min(50, engine_count()))
        for name in sample:
            e = get_engine(name)
            self.assertIsNotNone(e, f"{name} returned None")
            self.assertTrue(hasattr(e, "run"), f"{name} missing run()")
            self.assertTrue(callable(e.run), f"{name}.run not callable")


class TestEngineStructure(unittest.TestCase):
    def test_engine_has_engine_name(self):
        """Every engine must have ENGINE_NAME."""
        sample = random.sample(list_engines(), min(50, engine_count()))
        for name in sample:
            e = get_engine(name)
            self.assertTrue(
                hasattr(e, "ENGINE_NAME"),
                f"{name} missing ENGINE_NAME",
            )

    def test_engine_name_matches_registry(self):
        """ENGINE_NAME should match the registry key."""
        sample = random.sample(list_engines(), min(30, engine_count()))
        for name in sample:
            e = get_engine(name)
            if hasattr(e, "ENGINE_NAME"):
                self.assertEqual(e.ENGINE_NAME, name, f"{name} ENGINE_NAME mismatch")


class TestEngineExecution(unittest.TestCase):
    def test_inventory_engine_runs(self):
        """Inventory engine should return success with valid input."""
        e = get_engine("inventory")
        result = e.run({
            "status": "success",
            "data": {
                "products": [
                    {"id": "p1", "title": "Widget", "current_stock": 100,
                     "daily_sales": 5, "cost": 10, "lead_time_days": 7}
                ],
            },
            "meta": {},
            "error": None,
        })
        self.assertEqual(result["status"], "success")
        self.assertIn("inventory_health", result["data"])
        self.assertIn("engine", result["meta"])

    def test_fraud_detection_runs(self):
        e = get_engine("fraud_detection")
        result = e.run({
            "status": "success",
            "data": {
                "order": {
                    "id": "ord_test", "email": "test@example.com",
                    "total_price": 50.0, "currency": "USD",
                    "shipping_address": {"country_code": "US", "province": "TX"},
                    "billing_address": {"country_code": "US", "province": "TX"},
                    "customer": {"id": "c1", "orders_count": 5, "total_spent": 200, "account_age_days": 90},
                },
                "device": {"user_agent": "Mozilla/5.0", "screen_resolution": "1920x1080",
                           "timezone": "America/Chicago"},
            },
            "meta": {},
            "error": None,
        })
        self.assertEqual(result["status"], "success")
        self.assertIn("verdict", result["data"])
        self.assertIn("risk_score", result["data"])

    def test_tax_engine_runs(self):
        e = get_engine("tax_engine")
        result = e.run({
            "status": "success",
            "data": {
                "transaction": {
                    "id": "txn_test", "date": "2026-04-01", "currency": "USD",
                    "line_items": [{"id": "li1", "product_id": "p1", "title": "Widget",
                                    "quantity": 1, "unit_price": 29.99,
                                    "product_category": "physical_good"}],
                },
                "origin_address": {"province": "TX", "zip": "75201", "country_code": "US"},
                "destination_address": {"province": "TX", "zip": "78701", "country_code": "US"},
                "customer": {"id": "c1", "tax_exempt": False},
                "tax_type": "auto",
            },
            "meta": {},
            "error": None,
        })
        self.assertEqual(result["status"], "success")
        self.assertIn("total_tax", result["data"])
        self.assertGreater(result["data"]["total_tax"], 0)

    def test_upsell_engine_runs(self):
        e = get_engine("upsell")
        result = e.run({
            "status": "success",
            "data": {
                "current_product": {"id": "p1", "title": "Basic Widget", "price": 29.99,
                                     "category": "electronics", "features": ["bluetooth"]},
                "customer": {"avg_order_value": 50, "total_orders": 3},
                "catalog": [
                    {"id": "p2", "title": "Pro Widget", "price": 49.99,
                     "category": "electronics", "features": ["bluetooth", "wifi"], "margin": 0.4},
                ],
            },
            "meta": {},
            "error": None,
        })
        self.assertEqual(result["status"], "success")
        self.assertIn("upsells", result["data"])

    def test_engine_handles_empty_data(self):
        """Engine should return error status, not crash."""
        e = get_engine("inventory")
        result = e.run({
            "status": "success",
            "data": {},
            "meta": {},
            "error": None,
        })
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])

    def test_engine_handles_upstream_failure(self):
        """Engine should propagate upstream failure."""
        e = get_engine("inventory")
        result = e.run({
            "status": "fail",
            "data": {},
            "meta": {},
            "error": "Upstream failed",
        })
        self.assertEqual(result["status"], "error")

    def test_engine_output_has_meta(self):
        """All engines should include meta with engine name and timing."""
        e = get_engine("kpi_tracking")
        result = e.run({
            "status": "success",
            "data": {"orders": [{"id": "o1", "total": 100, "date": "2026-04-01"}],
                     "customers": [{"id": "c1"}], "costs": {}, "period": {}},
            "meta": {},
            "error": None,
        })
        self.assertIn("meta", result)
        self.assertIn("engine", result["meta"])
        self.assertIn("elapsed_seconds", result["meta"])

    def test_mass_engine_import(self):
        """All 95 engines must load without error."""
        errors = []
        for name in list_engines():
            e = get_engine(name)
            if e is None:
                errors.append(name)
        self.assertEqual(len(errors), 0, f"Failed to load: {errors}")


if __name__ == "__main__":
    unittest.main()
