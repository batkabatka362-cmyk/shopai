"""Intelligence module tests — real algorithm verification."""
import unittest


class TestPricingIntelligence(unittest.TestCase):
    def setUp(self):
        from core.intelligence import PricingIntelligence
        self.pi = PricingIntelligence()

    def test_demand_curve(self):
        result = self.pi.compute_demand_curve([
            {"price": 19.99, "units_sold": 250},
            {"price": 24.99, "units_sold": 180},
            {"price": 29.99, "units_sold": 120},
            {"price": 34.99, "units_sold": 75},
        ])
        self.assertIn("elasticity", result)
        self.assertLess(result["elasticity"], 0)  # Negative = demand drops as price rises
        self.assertGreater(result["r_squared"], 0.9)  # Good fit
        self.assertIn("optimal_price", result)

    def test_demand_curve_insufficient_data(self):
        result = self.pi.compute_demand_curve([{"price": 10, "units_sold": 100}])
        self.assertIn("error", result)

    def test_optimal_price_for_profit(self):
        result = self.pi.optimal_price_for_profit(10, [20, 25, 30, 35], [200, 150, 100, 60])
        self.assertIn("optimal_price", result)
        self.assertGreater(result["expected_profit"], 0)
        self.assertEqual(result["cost"], 10)

    def test_competitor_response(self):
        result = self.pi.competitor_response(29.99, 10, [
            {"price": 24.99}, {"price": 32.99}, {"price": 27.99},
        ])
        self.assertIn("position", result)
        self.assertIn("price_index", result)
        self.assertIn("recommended_action", result)
        self.assertGreater(result["competitor_count"], 0)

    def test_competitor_response_no_data(self):
        result = self.pi.competitor_response(29.99, 10, [])
        self.assertEqual(result["position"], "no_data")

    def test_ab_test_significant(self):
        result = self.pi.ab_test_analysis(
            {"price": 29.99, "visitors": 5000, "conversions": 200, "revenue": 5998},
            {"price": 24.99, "visitors": 5000, "conversions": 280, "revenue": 6997},
        )
        self.assertTrue(result["significant"])
        self.assertEqual(result["winner"], "B")
        self.assertGreater(result["lift_pct"], 0)

    def test_ab_test_not_significant(self):
        result = self.pi.ab_test_analysis(
            {"price": 29.99, "visitors": 50, "conversions": 5, "revenue": 150},
            {"price": 24.99, "visitors": 50, "conversions": 6, "revenue": 150},
        )
        self.assertFalse(result["significant"])
        self.assertFalse(result["sample_size_adequate"])


class TestRecommendationIntelligence(unittest.TestCase):
    def setUp(self):
        from core.intelligence import RecommendationIntelligence
        self.ri = RecommendationIntelligence()
        self.history = [
            {"customer_id": "c1", "product_id": "earbuds"},
            {"customer_id": "c1", "product_id": "case"},
            {"customer_id": "c1", "product_id": "charger"},
            {"customer_id": "c2", "product_id": "earbuds"},
            {"customer_id": "c2", "product_id": "case"},
            {"customer_id": "c2", "product_id": "cable"},
            {"customer_id": "c3", "product_id": "earbuds"},
            {"customer_id": "c3", "product_id": "charger"},
        ]

    def test_collaborative_filter(self):
        result = self.ri.collaborative_filter(self.history, "c1")
        self.assertEqual(result["method"], "collaborative")
        self.assertGreater(len(result["recommendations"]), 0)
        # c1 has earbuds+case+charger, c2 also has earbuds+case → should recommend cable
        product_ids = [r["product_id"] for r in result["recommendations"]]
        self.assertIn("cable", product_ids)

    def test_collaborative_filter_cold_start(self):
        result = self.ri.collaborative_filter(self.history, "new_customer")
        self.assertEqual(result["method"], "popularity_fallback")
        self.assertGreater(len(result["recommendations"]), 0)

    def test_content_based(self):
        products = [
            {"id": "1", "name": "Earbuds", "price": 30, "category": "electronics", "tags": ["wireless"]},
            {"id": "2", "name": "Headphones", "price": 50, "category": "electronics", "tags": ["wireless"]},
            {"id": "3", "name": "Yoga Mat", "price": 40, "category": "fitness", "tags": ["exercise"]},
        ]
        result = self.ri.content_based(products, products[0])
        self.assertGreater(len(result["recommendations"]), 0)
        # Headphones should be most similar to Earbuds (same category + tag)
        self.assertEqual(result["recommendations"][0]["product_id"], "2")

    def test_frequently_bought_together(self):
        orders = [
            {"order_id": "o1", "items": ["earbuds", "case"]},
            {"order_id": "o2", "items": ["earbuds", "case", "cable"]},
            {"order_id": "o3", "items": ["earbuds", "charger"]},
            {"order_id": "o4", "items": ["mat", "bands"]},
        ]
        result = self.ri.frequently_bought_together(orders, "earbuds")
        self.assertEqual(result["target_appearances"], 3)
        self.assertGreater(len(result["pairs"]), 0)
        # Case appears with earbuds in 2/3 orders
        self.assertEqual(result["pairs"][0]["product_id"], "case")

    def test_cart_cross_sell(self):
        cart = [{"name": "Earbuds", "price": 30, "category": "electronics"}]
        catalog = [
            {"name": "Case", "price": 15, "category": "accessories"},
            {"name": "Yoga Mat", "price": 40, "category": "fitness"},
        ]
        result = self.ri.cart_cross_sell(cart, catalog)
        self.assertGreater(len(result["suggestions"]), 0)
        # Case should rank higher (accessories complements electronics)
        self.assertEqual(result["suggestions"][0]["name"], "Case")


class TestEmailIntelligence(unittest.TestCase):
    def setUp(self):
        from core.intelligence import EmailIntelligence
        self.ei = EmailIntelligence()

    def test_score_good_subject(self):
        result = self.ei.score_subject_line("Your exclusive 20% off expires tonight")
        self.assertGreaterEqual(result["score"], 70)
        self.assertIn(result["grade"], ["A", "B"])

    def test_score_bad_subject(self):
        result = self.ei.score_subject_line("BUY NOW!!!! AMAZING DEAL $$$")
        self.assertLessEqual(result["score"], 45)
        self.assertIn(result["grade"], ["D", "F"])

    def test_score_empty_subject(self):
        result = self.ei.score_subject_line("")
        self.assertEqual(result["score"], 0)

    def test_subject_has_improvements(self):
        result = self.ei.score_subject_line("New stuff")
        self.assertGreater(len(result["improvements"]), 0)

    def test_abandoned_cart_flow(self):
        flow = self.ei.build_automation_flow("abandoned_cart")
        self.assertEqual(flow["name"], "Abandoned Cart Recovery")
        self.assertGreater(len(flow["emails"]), 0)
        self.assertIn("exit_condition", flow)

    def test_welcome_flow(self):
        flow = self.ei.build_automation_flow("welcome")
        self.assertEqual(len(flow["emails"]), 4)

    def test_all_flows_available(self):
        for flow_type in ["welcome", "abandoned_cart", "post_purchase", "win_back", "browse_abandonment", "vip"]:
            flow = self.ei.build_automation_flow(flow_type)
            self.assertIn("emails", flow, f"Flow {flow_type} missing emails")
            self.assertGreater(len(flow["emails"]), 0)

    def test_unknown_flow(self):
        result = self.ei.build_automation_flow("nonexistent_flow")
        self.assertIn("error", result)

    def test_optimal_send_time(self):
        result = self.ei.optimal_send_time({"timezone_offset": 8})
        self.assertIn("optimal_hour_utc", result)
        self.assertIn("optimal_hour_local", result)


class TestSEOIntelligence(unittest.TestCase):
    def setUp(self):
        from core.intelligence import SEOIntelligence
        self.si = SEOIntelligence()

    def test_audit_perfect_page(self):
        result = self.si.audit_page({
            "title": "Best Wireless Earbuds 2024 — Premium Sound Quality",
            "meta_description": "Discover the best wireless earbuds of 2024. Premium noise cancelling, 30hr battery, free shipping. Shop now and save 20%.",
            "h1": "Best Wireless Earbuds 2024",
            "content": " ".join(["Premium wireless earbuds with noise cancelling."] * 200),
            "url": "/products/best-wireless-earbuds",
            "keyword": "wireless earbuds",
            "images": [{"src": "1.jpg", "alt": "earbuds front"}],
            "internal_links": ["/collections/electronics", "/products/earbuds-case", "/blog/earbuds-guide"],
        })
        self.assertGreaterEqual(result["score"], 80)
        self.assertIn(result["grade"], ["A", "B"])

    def test_audit_bad_page(self):
        result = self.si.audit_page({})  # Empty page
        self.assertLessEqual(result["score"], 50)
        self.assertGreater(result["issue_count"], 0)

    def test_audit_missing_title(self):
        result = self.si.audit_page({"content": "Some content here " * 50})
        critical = [i for i in result["issues"] if i["severity"] == "critical"]
        self.assertGreater(len(critical), 0)

    def test_keyword_difficulty_short_tail(self):
        result = self.si.keyword_difficulty("earbuds")
        self.assertGreaterEqual(result["difficulty"], 60)
        self.assertEqual(result["keyword_type"], "short_tail")

    def test_keyword_difficulty_long_tail(self):
        result = self.si.keyword_difficulty("best noise cancelling earbuds under 50 dollars")
        self.assertLessEqual(result["difficulty"], 30)
        self.assertEqual(result["keyword_type"], "long_tail")

    def test_content_gap(self):
        result = self.si.content_gap(
            [{"title": "earbuds guide", "keywords": ["earbuds", "wireless"]}],
            [{"title": "earbuds guide", "keywords": ["earbuds", "bluetooth", "noise cancelling"]},
             {"title": "headphones review", "keywords": ["headphones", "review"]}],
        )
        self.assertGreater(result["total_gaps"], 0)
        self.assertIn("coverage_pct", result)


class TestIntelligenceWiring(unittest.TestCase):
    """Test that intelligence modules are actually used in engine runs."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_pricing_engine_has_demand_curve(self):
        from engines.base.engine_types import EngineInput
        from engines.registry import get_engine
        e = get_engine("pricing")
        out = e.run(EngineInput(task_id="wire_p", engine_name="pricing", data={
            "products": [{"name": "X", "price": 30, "cost": 10}],
            "sales_history": [
                {"price": 20, "units_sold": 200}, {"price": 25, "units_sold": 150},
                {"price": 30, "units_sold": 100}, {"price": 35, "units_sold": 60},
            ],
        }))
        self.assertIn("demand_curve", out.result)
        self.assertIn("elasticity", out.result["demand_curve"])

    def test_search_optimization_engine_loads(self):
        from engines.registry import get_engine
        e = get_engine("search_optimization")
        self.assertIsNotNone(e)

    def test_customer_engine_has_recommendations(self):
        from engines.base.engine_types import EngineInput
        from engines.registry import get_engine
        e = get_engine("customer_segmentation")
        out = e.run(EngineInput(task_id="wire_c", engine_name="customer_segmentation", data={
            "customer_data": [{"name": "A", "id": "c1", "orders": 5, "total_spent": 200, "days_since_last_order": 10}],
            "segmentation_criteria": {},
            "purchase_history": [
                {"customer_id": "c1", "product_id": "earbuds"},
                {"customer_id": "c1", "product_id": "case"},
                {"customer_id": "c2", "product_id": "earbuds"},
                {"customer_id": "c2", "product_id": "cable"},
            ],
        }))
        recs = out.result.get("product_recommendations", {})
        self.assertIn("recommendations", recs)


if __name__ == "__main__":
    unittest.main()
