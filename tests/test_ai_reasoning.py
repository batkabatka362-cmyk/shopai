"""Tests for AI reasoning layer and product research engine."""
import pytest


class TestAIReasoning:
    """Test the AI reasoning layer."""

    def test_init(self):
        from core.ai.reasoning import AIReasoning
        ai = AIReasoning()
        assert ai is not None

    def test_reason_pricing(self):
        from core.ai.reasoning import ai_reason
        products = [
            {"name": "Widget A", "price": 49.99, "cost": 15, "inventory_quantity": 100, "competition": 3},
            {"name": "Widget B", "price": 19.99, "cost": 18, "inventory_quantity": 50, "competition": 7},
        ]
        result = ai_reason("pricing", products=products)
        assert "analysis" in result
        assert "recommendations" in result
        assert "confidence" in result
        assert result["source"] in ("llm", "heuristic", "cache")

    def test_reason_pricing_low_margin(self):
        from core.ai.reasoning import ai_reason
        products = [{"name": "Bad Margin", "price": 20, "cost": 18, "inventory_quantity": 50}]
        result = ai_reason("pricing_optimization", products=products)
        recs = result.get("recommendations", [])
        # Should recommend raising price for low margin product
        assert len(recs) > 0

    def test_reason_product_selection(self):
        from core.ai.reasoning import ai_reason
        products = [
            {"name": "Hot Product", "price": 39.99, "cost": 8, "search_volume": 15000,
             "competition": 2, "rating": 4.8, "reviews": 500, "weight": 0.2},
            {"name": "Weak Product", "price": 10, "cost": 9, "search_volume": 100,
             "competition": 9, "rating": 2.5, "reviews": 3, "weight": 5.0},
        ]
        result = ai_reason("product_selection", products=products)
        recs = result.get("recommendations", [])
        assert len(recs) >= 2
        # Hot Product should rank higher
        assert recs[0]["product"] == "Hot Product"
        assert recs[0]["verdict"] == "strong_buy"

    def test_reason_customer_segmentation(self):
        from core.ai.reasoning import ai_reason
        customers = [
            {"name": "VIP", "orders": 10, "total_spent": 800, "days_since_last_order": 5},
            {"name": "At Risk", "orders": 3, "total_spent": 200, "days_since_last_order": 90},
            {"name": "New", "orders": 1, "total_spent": 30, "days_since_last_order": 10},
        ]
        result = ai_reason("customer_segmentation", customer_data=customers)
        assert "segments" in result
        assert result["segments"]["champions"] >= 1
        assert result["segments"]["at_risk"] >= 1

    def test_reason_inventory(self):
        from core.ai.reasoning import ai_reason
        products = [
            {"name": "Out of Stock", "inventory_quantity": 0, "velocity": 5},
            {"name": "Overstocked", "inventory_quantity": 500, "velocity": 0.1},
        ]
        result = ai_reason("inventory_management", products=products)
        recs = result.get("recommendations", [])
        assert len(recs) >= 2
        # First should be critical (out of stock)
        priorities = [r.get("priority") for r in recs]
        assert "critical" in priorities

    def test_reason_general_task(self):
        from core.ai.reasoning import ai_reason
        result = ai_reason("unknown_task", some_data="test")
        assert "analysis" in result
        assert result["confidence"] == 0.5

    def test_reason_caching(self):
        from core.ai.reasoning import ai_reason
        result1 = ai_reason("pricing", products=[{"name": "X", "price": 10, "cost": 5}])
        result2 = ai_reason("pricing", products=[{"name": "X", "price": 10, "cost": 5}])
        # Second call should be cached
        assert result2.get("source") == "cache"

    def test_is_llm_available(self):
        from core.ai.reasoning import is_llm_available
        # In test environment, likely no Ollama running
        result = is_llm_available()
        assert isinstance(result, bool)

    def test_build_prompt(self):
        from core.ai.reasoning import AIReasoning
        ai = AIReasoning()
        prompt = ai._build_prompt("pricing", {"products": [{"name": "Test", "price": 10}]})
        assert "pricing" in prompt
        assert "Test" in prompt
        assert "JSON" in prompt

    def test_extract_recommendations(self):
        from core.ai.reasoning import AIReasoning
        text = """Here are my recommendations:
- Lower price on Widget A to $29.99
- Restock Widget B immediately
* Consider bundling products
1. Monitor competitor pricing
You should also check inventory levels"""
        recs = AIReasoning._extract_recommendations(text)
        assert len(recs) >= 4

    def test_summarize_data(self):
        from core.ai.reasoning import AIReasoning
        data = {
            "products": [{"name": "A", "price": 10}, {"name": "B", "price": 20}],
            "store_id": "test",
        }
        summary = AIReasoning._summarize_data(data)
        assert "products" in summary
        assert "test" in summary


class TestProductResearchEngine:
    """Test the winning product finder."""

    def test_run_basic(self):
        from engines.product_research.flow import run
        result = run({"products": [
            {"name": "Good Product", "price": 39.99, "cost": 8, "search_volume": 12000,
             "competition": 3, "rating": 4.7, "reviews": 300, "weight": 0.3},
        ]})
        assert result["status"] == "success"
        assert len(result["data"]["winners"]) > 0

    def test_scoring(self):
        from engines.product_research.flow import run
        result = run({"products": [
            {"name": "Winner", "price": 29.99, "cost": 5, "search_volume": 15000,
             "competition": 2, "rating": 4.8, "reviews": 500, "weight": 0.2},
            {"name": "Loser", "price": 5, "cost": 4.5, "search_volume": 50,
             "competition": 9, "rating": 2.0, "reviews": 2, "weight": 10},
        ]})
        winners = result["data"]["winners"]
        assert winners[0]["product"] == "Winner"
        assert winners[0]["verdict"] == "strong_buy"
        assert winners[1]["verdict"] in ("skip", "consider")

    def test_empty_products(self):
        from engines.product_research.flow import run
        result = run({"products": []})
        assert result["status"] == "success"
        assert result["data"]["winners"] == []

    def test_opportunities(self):
        from engines.product_research.flow import run
        result = run({"products": [
            {"name": "High Margin", "price": 50, "cost": 10, "competition": 3},
        ]})
        assert "opportunities" in result["data"]

    def test_trends_default(self):
        from engines.product_research.flow import run
        result = run({"products": []})
        assert len(result["data"]["trends"]) > 0

    def test_registered_in_registry(self):
        from engines.registry import get_engine
        engine = get_engine("product_research")
        assert engine is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
