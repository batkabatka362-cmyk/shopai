"""Tests for Multi-Model Architecture: ModelCoordinator, LearningModel."""
import tempfile
import os
import pytest

# Disable LLM for tests
os.environ["SHOPAI_OLLAMA_URL"] = "http://invalid:1234"


class TestModelCoordinator:
    def test_init(self):
        from core.brain.model_coordinator import ModelCoordinator
        coord = ModelCoordinator()
        assert coord is not None

    def test_stats_empty(self):
        from core.brain.model_coordinator import ModelCoordinator
        coord = ModelCoordinator()
        stats = coord.get_stats()
        assert stats["total_executions"] == 0

    def test_start_learning(self):
        from core.brain.model_coordinator import ModelCoordinator
        coord = ModelCoordinator()
        result = coord.start_learning({"products": [{"name": "X", "price": 20, "cost": 8}]})
        assert result["status"] == "started"
        # Wait for learning thread
        import time
        time.sleep(0.5)
        results = coord.get_learning_results()
        assert len(results) >= 1

    def test_start_learning_already_running(self):
        from core.brain.model_coordinator import ModelCoordinator
        coord = ModelCoordinator()
        coord._learning_running = True
        result = coord.start_learning({})
        assert result["status"] == "already_running"


class TestLearningModel:
    def test_init(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        assert model is not None

    def test_analyze_data(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        analysis = model.analyze_data({
            "products": [
                {"name": "A", "price": 30, "cost": 10, "category": "Home"},
                {"name": "B", "price": 20, "cost": 8, "category": "Home"},
                {"name": "C", "price": 50, "cost": 20, "category": "Electronics"},
            ],
            "orders": [{"total": 80}],
            "customers": [{"orders": 3}, {"orders": 1}],
        })
        assert analysis["products"]["count"] == 3
        assert analysis["products"]["avg_margin"] > 0.5
        assert analysis["orders"]["count"] == 1
        assert analysis["health_score"] > 50

    def test_analyze_data_no_orders(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        analysis = model.analyze_data({"products": [{"price": 20}], "orders": []})
        assert analysis["orders"]["critical"] == "NO SALES — top priority"

    def test_find_patterns(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        patterns = model.find_patterns({
            "products": [
                {"name": "A", "price": 50, "cost": 15, "category": "Home", "inventory_quantity": 5},
                {"name": "B", "price": 25, "cost": 8, "category": "Home", "inventory_quantity": 50},
                {"name": "C", "price": 15, "cost": 5, "category": "Home", "inventory_quantity": 3},
            ],
        })
        assert len(patterns) > 0
        types = [p["type"] for p in patterns]
        assert "price_tier_margin" in types

    def test_find_category_concentration(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        products = [{"name": f"P{i}", "price": 20, "cost": 8, "category": "Home"} for i in range(8)]
        products.append({"name": "X", "price": 30, "cost": 10, "category": "Electronics"})
        patterns = model.find_patterns({"products": products})
        types = [p["type"] for p in patterns]
        assert "category_concentration" in types

    def test_generate_rules(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        patterns = [
            {"type": "price_tier_margin", "tier": "mid", "avg_margin": 0.65, "count": 5},
            {"type": "inventory_risk", "count": 3},
        ]
        rules = model.generate_rules(patterns)
        assert len(rules) >= 2
        actions = [r["action"] for r in rules]
        assert "keep" in actions
        assert "restock" in actions

    def test_simulate_strategies(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        sims = model.simulate_strategies({
            "products": [
                {"name": "A", "price": 30, "cost": 10},
                {"name": "B", "price": 20, "cost": 8},
            ],
        })
        assert len(sims) == 3
        names = [s["name"] for s in sims]
        assert "raise_all_10pct" in names
        assert "focus_top5_margin" in names

    def test_simulate_empty(self):
        from core.brain.learning_model import LearningModel
        model = LearningModel()
        sims = model.simulate_strategies({"products": []})
        assert sims == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
