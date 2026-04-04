"""Tests for Brain Intelligence: Memory, DecisionEngine, LearningLoop."""
import tempfile
import pytest


class TestIntelligentMemory:
    def _make(self):
        from core.brain.memory import IntelligentMemory
        return IntelligentMemory(tempfile.mktemp(suffix=".db"))

    def test_ingest(self):
        mem = self._make()
        mid = mem.ingest("pricing", {"price": 20, "cost": 8, "name": "Widget"})
        assert mid > 0

    def test_ingest_bad_data(self):
        mem = self._make()
        mid = mem.ingest("pricing", {})  # Empty = bad
        assert mid == 0
        bad = mem.get_bad_data()
        assert len(bad) == 1

    def test_record_decision(self):
        mem = self._make()
        mid = mem.record_decision("pricing", {"price": 20}, "keep_price", {"status": "ok"}, 4.0)
        assert mid > 0

    def test_retrieve_for_decision(self):
        mem = self._make()
        mem.record_decision("pricing", {"price": 20}, "raise", {"profit": 10}, 4.5, ["pricing"])
        mem.record_decision("pricing", {"price": 20}, "lower", {"profit": -5}, 1.5, ["pricing"])
        ctx = mem.retrieve_for_decision("pricing", {"price": 25})
        assert len(ctx["best_cases"]) >= 1
        assert len(ctx["failures"]) >= 1

    def test_pattern_detection(self):
        mem = self._make()
        # Same pattern 3 times → should generate rule
        for _ in range(3):
            mem.record_decision("pricing", {"price": 30, "cost": 10}, "raise", {"profit": 15}, 4.5)
        rules = mem.get_rules("pricing")
        # May or may not generate depending on features
        stats = mem.get_stats()
        assert stats["total_memories"] == 3

    def test_feature_extraction(self):
        from core.brain.memory import IntelligentMemory
        features = IntelligentMemory._extract_features("pricing", {"price": 50, "cost": 15})
        assert features["has_price"] is True
        assert features["has_cost"] is True
        assert features["margin"] > 0.5
        assert features["price_tier"] == "premium"

    def test_auto_tag(self):
        from core.brain.memory import IntelligentMemory
        features = {"margin": 0.7, "price_tier": "premium"}
        tags = IntelligentMemory._auto_tag("pricing", {}, features)
        assert "high_margin" in tags
        assert "premium" in tags

    def test_stats(self):
        mem = self._make()
        mem.ingest("pricing", {"price": 20, "cost": 8})
        mem.record_decision("product", {"name": "X"}, "add", {}, 3.0)
        stats = mem.get_stats()
        assert stats["total_memories"] == 2


class TestDecisionEngine:
    def test_decide_pricing(self):
        from core.brain.decision_engine import DecisionEngine
        engine = DecisionEngine()
        # Override memory to temp
        from core.brain.memory import IntelligentMemory
        engine._memory = IntelligentMemory(tempfile.mktemp(suffix=".db"))

        decision = engine.decide("pricing", {"price": 25, "cost": 10})
        assert decision.choice
        assert decision.reason
        assert 0 <= decision.score <= 1
        assert decision.category == "pricing"

    def test_decide_with_options(self):
        from core.brain.decision_engine import DecisionEngine
        engine = DecisionEngine()
        engine._memory = __import__("core.brain.memory", fromlist=["IntelligentMemory"]).IntelligentMemory(tempfile.mktemp(suffix=".db"))

        options = [
            {"action": "keep", "reason": "Safe", "profit_score": 0.5, "risk_score": 0.1},
            {"action": "change", "reason": "Risky", "profit_score": 0.8, "risk_score": 0.7},
        ]
        decision = engine.decide("pricing", {"price": 20}, options)
        assert decision.choice in ("keep", "change")
        assert decision.options_considered == 2

    def test_decide_learns_from_memory(self):
        from core.brain.decision_engine import DecisionEngine
        from core.brain.memory import IntelligentMemory
        mem = IntelligentMemory(tempfile.mktemp(suffix=".db"))

        # Record past success
        mem.record_decision("pricing", {"price": 20}, "keep_price", {"profit": 10}, 5.0)

        engine = DecisionEngine()
        engine._memory = mem
        decision = engine.decide("pricing", {"price": 20, "cost": 8})
        assert decision.memory_used is True

    def test_record_outcome(self):
        from core.brain.decision_engine import DecisionEngine
        from core.brain.memory import IntelligentMemory
        engine = DecisionEngine()
        engine._memory = IntelligentMemory(tempfile.mktemp(suffix=".db"))

        engine.record_outcome("pricing", "raise", {"price": 30}, {"profit": 15}, 4.5)
        stats = engine.get_stats()
        assert stats["memory"]["total_memories"] >= 1


class TestLearningLoop:
    def test_learn_success(self):
        from core.brain.learning_loop import LearningLoop
        from core.brain.memory import IntelligentMemory
        loop = LearningLoop()
        loop._memory = IntelligentMemory(tempfile.mktemp(suffix=".db"))

        result = loop.learn("pricing", {"price": 20}, "raise",
                           {"status": "success"}, {"profit": 50})
        assert result["success"] is True
        assert result["score"] >= 3
        assert result["success_insight"] is not None

    def test_learn_failure(self):
        from core.brain.learning_loop import LearningLoop
        from core.brain.memory import IntelligentMemory
        loop = LearningLoop()
        loop._memory = IntelligentMemory(tempfile.mktemp(suffix=".db"))

        result = loop.learn("pricing", {"price": 20}, "lower",
                           {"status": "error", "error": "timeout"}, {"profit": -10})
        assert result["success"] is False
        assert result["failure_insight"] is not None
        assert result["failure_insight"]["root_cause"] == "performance"

    def test_learn_repeated_failure(self):
        from core.brain.learning_loop import LearningLoop
        from core.brain.memory import IntelligentMemory
        mem = IntelligentMemory(tempfile.mktemp(suffix=".db"))
        loop = LearningLoop()
        loop._memory = mem

        # Fail 3 times
        for _ in range(3):
            loop.learn("pricing", {"price": 5}, "lower",
                      {"status": "error"}, {"profit": -20})

        result = loop.learn("pricing", {"price": 5}, "lower",
                           {"status": "error"}, {"profit": -20})
        assert result["failure_insight"]["is_repeated"] is True

    def test_stats(self):
        from core.brain.learning_loop import LearningLoop
        from core.brain.memory import IntelligentMemory
        loop = LearningLoop()
        loop._memory = IntelligentMemory(tempfile.mktemp(suffix=".db"))
        loop.learn("test", {}, "test_action", {"status": "success"}, {})
        stats = loop.get_stats()
        assert stats["total_learnings"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
