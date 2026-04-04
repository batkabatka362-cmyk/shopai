"""Test suite for P1 engines — browse_recovery, loyalty, supplier_communication,
competitor_monitor, store_design, legal_document, checkout_optimizer.

Each test provides realistic sample data and verifies the engine contract:
  Input:  {status, data, meta, error}
  Output: {status, data, meta: {engine, elapsed_seconds}, error}
"""
import unittest
from engines.registry import get_engine


def _payload(data: dict) -> dict:
    """Build a standard engine input payload."""
    return {"status": "success", "data": data, "meta": {}, "error": None}


def _empty_payload() -> dict:
    return {"status": "success", "data": {}, "meta": {}, "error": None}


def _fail_payload(reason: str = "upstream broke") -> dict:
    return {"status": "fail", "data": {}, "meta": {}, "error": reason}


# ======================================================================
# Browse Recovery
# ======================================================================


class TestBrowseRecovery(unittest.TestCase):
    """Tests for the browse_recovery engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("browse_recovery")
        assert cls.engine is not None, "browse_recovery engine not found"

    def test_recovers_browse_abandoners(self):
        """Sessions with viewed products should produce recovery_targets."""
        result = self.engine.run(_payload({
            "sessions": [
                {
                    "user_id": "u1",
                    "pages_viewed": ["/", "/products/widget", "/products/gadget"],
                    "products_viewed": ["widget", "gadget"],
                    "duration": 180,
                    "cart_items": [],
                },
                {
                    "user_id": "u2",
                    "pages_viewed": ["/", "/products/gizmo"],
                    "products_viewed": ["gizmo"],
                    "duration": 60,
                    "cart_items": [],
                },
            ],
            "products": [
                {"id": "widget", "title": "Widget", "price": 29.99},
                {"id": "gadget", "title": "Gadget", "price": 49.99},
                {"id": "gizmo", "title": "Gizmo", "price": 19.99},
            ],
        }))
        self.assertEqual(result["status"], "success")
        self.assertIn("recovery_targets", result["data"])
        self.assertIsInstance(result["data"]["recovery_targets"], list)
        self.assertGreater(len(result["data"]["recovery_targets"]), 0)
        self.assertIn("total_recoverable", result["data"])
        self.assertIn("estimated_revenue", result["data"])
        self.assertIn("engine", result["meta"])
        self.assertEqual(result["meta"]["engine"], "browse_recovery")
        self.assertIn("elapsed_seconds", result["meta"])

    def test_empty_sessions(self):
        """Empty sessions list should return an error."""
        result = self.engine.run(_payload({
            "sessions": [],
            "products": [],
        }))
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])

    def test_upstream_failure_propagated(self):
        """Upstream failure status should be propagated as error."""
        result = self.engine.run(_fail_payload())
        self.assertEqual(result["status"], "error")

    def test_missing_data_key(self):
        """Missing data entirely should return error."""
        result = self.engine.run(_empty_payload())
        self.assertEqual(result["status"], "error")


# ======================================================================
# Loyalty
# ======================================================================


class TestLoyalty(unittest.TestCase):
    """Tests for the loyalty engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("loyalty")
        assert cls.engine is not None, "loyalty engine not found"

    def test_designs_program(self):
        """Given customers and orders, should produce program with tiers and points."""
        result = self.engine.run(_payload({
            "customers": [
                {"id": "c1", "name": "Alice", "email": "alice@example.com", "total_spent": 500},
                {"id": "c2", "name": "Bob", "email": "bob@example.com", "total_spent": 150},
                {"id": "c3", "name": "Charlie", "email": "charlie@example.com", "total_spent": 2000},
            ],
            "orders": [
                {"id": "o1", "customer_id": "c1", "total": 100, "date": "2026-03-01"},
                {"id": "o2", "customer_id": "c1", "total": 400, "date": "2026-03-15"},
                {"id": "o3", "customer_id": "c2", "total": 150, "date": "2026-03-10"},
                {"id": "o4", "customer_id": "c3", "total": 2000, "date": "2026-02-01"},
            ],
            "program_config": {},
            "current_points": {},
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("program", data)
        self.assertIn("tiers", data["program"])
        self.assertIsInstance(data["program"]["tiers"], list)
        self.assertIn("point_rules", data["program"])
        self.assertIn("customer_status", data)
        self.assertIn("program_health", data)
        self.assertEqual(result["meta"]["engine"], "loyalty")

    def test_calculates_points(self):
        """Points calculation should produce non-empty customer_status."""
        result = self.engine.run(_payload({
            "customers": [
                {"id": "c1", "name": "Test User", "email": "test@example.com", "total_spent": 300},
            ],
            "orders": [
                {"id": "o1", "customer_id": "c1", "total": 300, "date": "2026-03-20"},
            ],
            "program_config": {},
            "current_points": {"c1": 100},
        }))
        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["data"]["customer_status"], list)
        self.assertGreater(len(result["data"]["customer_status"]), 0)

    def test_empty_customers(self):
        """Empty customer list should return error."""
        result = self.engine.run(_payload({
            "customers": [],
            "orders": [],
        }))
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])


# ======================================================================
# Supplier Communication
# ======================================================================


class TestSupplierCommunication(unittest.TestCase):
    """Tests for the supplier_communication engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("supplier_communication")
        assert cls.engine is not None, "supplier_communication engine not found"

    def test_generates_po(self):
        """Given suppliers and reorder plan, should produce purchase_orders."""
        result = self.engine.run(_payload({
            "suppliers": [
                {"id": "s1", "name": "Acme Supplies", "email": "orders@acme.com",
                 "products": ["widget", "gadget"], "lead_time_days": 7, "min_order": 50},
            ],
            "reorder_plan": [
                {"product_id": "widget", "supplier_id": "s1", "quantity": 100, "urgency": "normal"},
                {"product_id": "gadget", "supplier_id": "s1", "quantity": 200, "urgency": "high"},
            ],
            "inventory_status": [
                {"product_id": "widget", "current_stock": 20, "daily_sales": 5},
                {"product_id": "gadget", "current_stock": 5, "daily_sales": 10},
            ],
            "communication_history": [],
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("purchase_orders", data)
        self.assertIsInstance(data["purchase_orders"], list)
        self.assertIn("messages", data)
        self.assertIn("tracking_updates", data)
        self.assertEqual(result["meta"]["engine"], "supplier_communication")

    def test_builds_messages(self):
        """Should generate messages for supplier communication."""
        result = self.engine.run(_payload({
            "suppliers": [
                {"id": "s1", "name": "Quick Parts", "email": "info@quickparts.com",
                 "products": ["bolt"], "lead_time_days": 3, "min_order": 10},
            ],
            "reorder_plan": [
                {"product_id": "bolt", "supplier_id": "s1", "quantity": 500, "urgency": "low"},
            ],
            "inventory_status": [],
            "communication_history": [
                {"supplier_id": "s1", "date": "2026-03-01", "type": "po", "status": "delivered"},
            ],
        }))
        self.assertEqual(result["status"], "success")
        self.assertIn("messages", result["data"])
        self.assertIsInstance(result["data"]["messages"], list)

    def test_empty_suppliers(self):
        """Empty supplier list should return error."""
        result = self.engine.run(_payload({
            "suppliers": [],
            "reorder_plan": [],
        }))
        self.assertEqual(result["status"], "error")


# ======================================================================
# Competitor Monitor
# ======================================================================


class TestCompetitorMonitor(unittest.TestCase):
    """Tests for the competitor_monitor engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("competitor_monitor")
        assert cls.engine is not None, "competitor_monitor engine not found"

    def test_detects_price_changes(self):
        """Given competitors with price diffs, should generate alerts."""
        result = self.engine.run(_payload({
            "competitors": [
                {
                    "name": "RivalCo",
                    "url": "https://rivalco.com",
                    "products": [
                        {"id": "rp1", "title": "Widget Pro", "price": 24.99,
                         "previous_price": 29.99, "category": "electronics"},
                        {"id": "rp2", "title": "Gadget Plus", "price": 39.99,
                         "previous_price": 39.99, "category": "electronics"},
                    ],
                },
                {
                    "name": "BudgetShop",
                    "url": "https://budgetshop.com",
                    "products": [
                        {"id": "bp1", "title": "Basic Widget", "price": 14.99,
                         "previous_price": 19.99, "category": "electronics"},
                    ],
                },
            ],
            "our_products": [
                {"id": "p1", "title": "Widget", "price": 29.99, "category": "electronics"},
                {"id": "p2", "title": "Gadget", "price": 44.99, "category": "electronics"},
            ],
            "alert_thresholds": {
                "price_change_pct": 5.0,
                "new_product_alert": True,
            },
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("price_changes", data)
        self.assertIn("alerts", data)
        self.assertIn("recommended_responses", data)
        self.assertIn("new_products", data)
        self.assertEqual(result["meta"]["engine"], "competitor_monitor")
        self.assertIn("elapsed_seconds", result["meta"])

    def test_empty_competitors(self):
        """Empty competitor list should return error."""
        result = self.engine.run(_payload({
            "competitors": [],
            "our_products": [],
        }))
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])


# ======================================================================
# Store Design
# ======================================================================


class TestStoreDesign(unittest.TestCase):
    """Tests for the store_design engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("store_design")
        assert cls.engine is not None, "store_design engine not found"

    def test_recommends_layout(self):
        """Given brand and products, should return layout recommendations."""
        result = self.engine.run(_payload({
            "brand": {
                "name": "TestBrand",
                "industry": "fashion",
                "style": "modern",
                "colors": {"primary": "#333333", "secondary": "#FF6600"},
                "target_audience": "young adults",
            },
            "products": [
                {"id": "p1", "title": "Summer Dress", "price": 59.99, "category": "dresses",
                 "images": 3},
                {"id": "p2", "title": "Winter Coat", "price": 129.99, "category": "outerwear",
                 "images": 4},
                {"id": "p3", "title": "Canvas Sneakers", "price": 79.99, "category": "shoes",
                 "images": 2},
            ],
            "analytics": {
                "bounce_rate": 0.45,
                "avg_session_duration": 120,
                "mobile_pct": 0.65,
                "top_pages": ["/", "/products", "/sale"],
            },
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("layout_recommendations", data)
        self.assertIsInstance(data["layout_recommendations"], list)
        self.assertIn("color_palette", data)
        self.assertIn("navigation", data)
        self.assertIn("mobile_optimizations", data)
        self.assertIn("estimated_conversion_lift", data)
        self.assertEqual(result["meta"]["engine"], "store_design")

    def test_minimal_brand_input(self):
        """Engine should work with minimal brand info."""
        result = self.engine.run(_payload({
            "brand": {"name": "MiniBrand"},
            "products": [],
            "analytics": {},
        }))
        self.assertEqual(result["status"], "success")
        self.assertIn("layout_recommendations", result["data"])


# ======================================================================
# Legal Document
# ======================================================================


class TestLegalDocument(unittest.TestCase):
    """Tests for the legal_document engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("legal_document")
        assert cls.engine is not None, "legal_document engine not found"

    def test_generates_terms(self):
        """Given business info, should generate legal documents."""
        result = self.engine.run(_payload({
            "business": {
                "name": "TestShop LLC",
                "country": "US",
                "state": "California",
                "industry": "e-commerce",
                "website": "https://testshop.com",
                "email": "legal@testshop.com",
                "sells_physical_goods": True,
                "collects_personal_data": True,
                "accepts_payments": True,
            },
            "policies": {
                "return_window_days": 30,
                "shipping_policy": "standard",
                "privacy_contact": "privacy@testshop.com",
            },
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("documents", data)
        self.assertIsInstance(data["documents"], list)
        self.assertGreater(len(data["documents"]), 0)
        self.assertIn("compliance_check", data)
        self.assertEqual(result["meta"]["engine"], "legal_document")

    def test_compliance_check(self):
        """Compliance validation should include check results and missing sections."""
        result = self.engine.run(_payload({
            "business": {
                "name": "ComplianceCo",
                "country": "US",
                "state": "New York",
                "industry": "retail",
                "website": "https://complianceco.com",
            },
            "policies": {},
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("compliance_check", data)
        self.assertIn("missing_sections", data)
        self.assertIsInstance(data["missing_sections"], list)

    def test_missing_business_name(self):
        """Business without name should return error."""
        result = self.engine.run(_payload({
            "business": {"country": "US"},
            "policies": {},
        }))
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])

    def test_empty_business(self):
        """Empty business dict should return error."""
        result = self.engine.run(_payload({
            "business": {},
            "policies": {},
        }))
        self.assertEqual(result["status"], "error")


# ======================================================================
# Checkout Optimizer
# ======================================================================


class TestCheckoutOptimizer(unittest.TestCase):
    """Tests for the checkout_optimizer engine."""

    @classmethod
    def setUpClass(cls):
        cls.engine = get_engine("checkout_optimizer")
        assert cls.engine is not None, "checkout_optimizer engine not found"

    def test_finds_friction(self):
        """Given checkout analytics, should identify friction_points."""
        result = self.engine.run(_payload({
            "checkout_config": {
                "steps": ["cart", "shipping", "payment", "review", "confirm"],
                "guest_checkout": True,
                "address_autocomplete": False,
                "one_click_pay": False,
                "coupon_field_visible": True,
                "progress_bar": False,
            },
            "analytics": {
                "cart_abandonment_rate": 0.72,
                "step_drop_off": {
                    "cart_to_shipping": 0.30,
                    "shipping_to_payment": 0.15,
                    "payment_to_review": 0.10,
                    "review_to_confirm": 0.05,
                },
                "avg_checkout_time_seconds": 240,
                "mobile_checkout_pct": 0.55,
                "payment_failure_rate": 0.08,
            },
            "payment_methods": [
                {"name": "credit_card", "enabled": True, "failure_rate": 0.05},
                {"name": "paypal", "enabled": True, "failure_rate": 0.03},
                {"name": "apple_pay", "enabled": False, "failure_rate": 0.01},
            ],
        }))
        self.assertEqual(result["status"], "success")
        data = result["data"]
        self.assertIn("friction_points", data)
        self.assertIsInstance(data["friction_points"], list)
        self.assertIn("optimizations", data)
        self.assertIn("trust_signals", data)
        self.assertIn("payment_recommendations", data)
        self.assertEqual(result["meta"]["engine"], "checkout_optimizer")
        self.assertIn("elapsed_seconds", result["meta"])

    def test_minimal_config(self):
        """Engine should handle minimal checkout config without crashing."""
        result = self.engine.run(_payload({
            "checkout_config": {},
            "analytics": {},
            "payment_methods": [],
        }))
        self.assertEqual(result["status"], "success")
        self.assertIn("friction_points", result["data"])

    def test_upstream_failure(self):
        """Upstream failure should be propagated."""
        result = self.engine.run(_fail_payload("payment gateway down"))
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
