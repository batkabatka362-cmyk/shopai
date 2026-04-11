"""Tests for ExternalTools, ExperienceAccumulator, and SelfImprover."""
import tempfile
import time
import pytest


class TestExternalTools:
    """Test external tools integration."""

    def test_init(self):
        from core.ai.external_tools import ExternalTools
        tools = ExternalTools()
        assert tools is not None

    def test_extract_prices(self):
        from core.ai.external_tools import ExternalTools
        prices = ExternalTools._extract_prices("This costs $29.99 and that is $49.99. Also $0.50 is too low.")
        assert 29.99 in prices
        assert 49.99 in prices
        assert 0.50 not in prices  # Below $1 filter

    def test_html_to_text(self):
        from core.ai.external_tools import ExternalTools
        html = "<html><head><title>Test</title></head><body><p>Hello <b>world</b></p><script>evil()</script></body></html>"
        text = ExternalTools._html_to_text(html)
        assert "Hello" in text
        assert "world" in text
        assert "evil" not in text
        assert "<" not in text

    def test_extract_tag(self):
        from core.ai.external_tools import ExternalTools
        html = "<html><title>My Store</title></html>"
        title = ExternalTools._extract_tag(html, "title")
        assert title == "My Store"

    def test_extract_meta(self):
        from core.ai.external_tools import ExternalTools
        html = '<meta name="description" content="Best store ever">'
        desc = ExternalTools._extract_meta(html, "description")
        assert desc == "Best store ever"

    def test_tool_stats_tracking(self):
        from core.ai.external_tools import ExternalTools
        tools = ExternalTools()
        tools._log_call("test_tool", True, 0.5, {"test": True})
        tools._log_call("test_tool", False, 1.0, {"test": True})
        stats = tools.get_tool_stats()
        assert "test_tool" in stats
        assert stats["test_tool"]["calls"] == 2
        assert stats["test_tool"]["successes"] == 1
        assert stats["test_tool"]["success_rate"] == 0.5

    def test_recent_calls(self):
        from core.ai.external_tools import ExternalTools
        tools = ExternalTools()
        tools._log_call("tool_a", True, 0.1, {})
        tools._log_call("tool_b", False, 0.2, {})
        calls = tools.get_recent_calls()
        assert len(calls) == 2

    def test_singleton(self):
        from core.ai.external_tools import get_tools
        t1 = get_tools()
        t2 = get_tools()
        assert t1 is t2


class TestExperienceAccumulator:
    """Test permanent knowledge storage."""

    def _make_exp(self):
        from core.ai.experience import ExperienceAccumulator
        tmp = tempfile.mktemp(suffix=".db")
        return ExperienceAccumulator(tmp)

    def test_init(self):
        exp = self._make_exp()
        assert exp is not None
        exp.close()

    def test_learn_product(self):
        exp = self._make_exp()
        exp.learn_product("p1", "pricing", "Best sold at $29.99", confidence=0.8)
        knowledge = exp.get_product_knowledge("p1")
        assert len(knowledge) == 1
        assert knowledge[0]["insight"] == "Best sold at $29.99"
        assert knowledge[0]["confidence"] == 0.8
        exp.close()

    def test_reinforce_knowledge(self):
        exp = self._make_exp()
        exp.learn_product("p1", "pricing", "Sells well in winter", confidence=0.6)
        exp.learn_product("p1", "pricing", "Sells well in winter", confidence=0.6)
        knowledge = exp.get_product_knowledge("p1")
        assert len(knowledge) == 1
        assert knowledge[0]["times_confirmed"] == 2
        assert knowledge[0]["confidence"] > 0.6  # Should increase
        exp.close()

    def test_record_decision_outcome(self):
        exp = self._make_exp()
        exp.record_decision_outcome(
            "pricing", {"product": "Widget", "old_price": 30, "new_price": 25},
            {"revenue_change": 15}, success=True, impact_score=0.7,
        )
        decisions = exp.get_similar_decisions("pricing")
        assert len(decisions) == 1
        assert decisions[0]["success"] == 1
        exp.close()

    def test_success_rate(self):
        exp = self._make_exp()
        exp.record_decision_outcome("test", {}, {}, success=True)
        exp.record_decision_outcome("test", {}, {}, success=True)
        exp.record_decision_outcome("test", {}, {}, success=False)
        rate = exp.get_success_rate("test")
        assert rate["total"] == 3
        assert rate["successes"] == 2
        assert abs(rate["success_rate"] - 0.667) < 0.01
        exp.close()

    def test_strategy_learning(self):
        exp = self._make_exp()
        exp.learn_strategy("Lower prices 10% for slow movers", "pricing", 0.8)
        exp.learn_strategy("Lower prices 10% for slow movers", "pricing", 0.9)
        strategies = exp.get_best_strategies("pricing")
        assert len(strategies) == 1
        assert strategies[0]["evidence_count"] == 2
        assert strategies[0]["effectiveness"] > 0.8
        exp.close()

    def test_mistake_recording(self):
        exp = self._make_exp()
        exp.record_mistake("overpricing", "Set price too high, lost sales",
                          cause="Ignored competitor prices", prevention="Always check competitors first")
        mistakes = exp.get_mistakes("overpricing")
        assert len(mistakes) == 1
        assert "too high" in mistakes[0]["description"]
        exp.close()

    def test_tool_knowledge(self):
        exp = self._make_exp()
        exp.update_tool_knowledge("web_search", "competitor_research", 0.85, 1.2, 50, "Finding competitor prices")
        best = exp.get_best_tool("competitor_research")
        assert best is not None
        assert best["tool_name"] == "web_search"
        exp.close()

    def test_market_intelligence(self):
        exp = self._make_exp()
        exp.store_market_intel("electronics", "Wireless earbuds demand up 30%", "web_search", 0.7)
        intel = exp.get_market_intel("electronics")
        assert len(intel) == 1
        assert "earbuds" in intel[0]["insight"]
        exp.close()

    def test_knowledge_summary(self):
        exp = self._make_exp()
        exp.learn_product("p1", "test", "test insight")
        exp.record_decision_outcome("test", {}, {}, success=True)
        exp.record_mistake("test", "test mistake")
        summary = exp.get_knowledge_summary()
        assert summary["product_insights"] == 1
        assert summary["decisions_recorded"] == 1
        assert summary["mistakes_logged"] == 1
        exp.close()


class TestSelfImprover:
    """Test self-improvement engine."""

    def test_init(self):
        from core.ai.self_improver import SelfImprover
        improver = SelfImprover()
        assert improver is not None

    def test_review_cycle_no_insights(self):
        from core.ai.self_improver import SelfImprover
        improver = SelfImprover()
        # Override experience to use temp DB
        from core.ai.experience import ExperienceAccumulator
        improver._experience = ExperienceAccumulator(tempfile.mktemp(suffix=".db"))

        result = improver.review_cycle({
            "phases": {
                "analysis": {"engines_run": 5, "insights": 0},
                "decisions": {"proposed": 0},
                "execution": {"executed": 0, "failed": 0},
                "learning": {"weight_updates": 0},
            },
            "duration_s": 2.5,
        })
        assert result["mistakes_found"] >= 1  # Should detect low insights

    def test_review_cycle_with_failures(self):
        from core.ai.self_improver import SelfImprover
        from core.ai.experience import ExperienceAccumulator
        improver = SelfImprover()
        improver._experience = ExperienceAccumulator(tempfile.mktemp(suffix=".db"))

        result = improver.review_cycle({
            "phases": {
                "analysis": {"engines_run": 3, "insights": 5},
                "decisions": {"proposed": 3},
                "execution": {"executed": 1, "failed": 2},
                "learning": {"weight_updates": 1},
            },
            "duration_s": 5,
        })
        assert result["mistakes_found"] >= 1  # Should detect execution failures

    def test_enhance_decision(self):
        from core.ai.self_improver import SelfImprover
        from core.ai.experience import ExperienceAccumulator
        improver = SelfImprover()
        exp = ExperienceAccumulator(tempfile.mktemp(suffix=".db"))
        improver._experience = exp

        # Record some history
        for _ in range(6):
            exp.record_decision_outcome("pricing", {"price": 25}, {"revenue": 100}, success=True)
        exp.record_decision_outcome("pricing", {"price": 25}, {"revenue": -10}, success=False)

        enhanced = improver.enhance_decision("pricing", {"type": "update_price", "confidence": 0.5})
        assert "confidence" in enhanced
        assert enhanced["experience_data_points"] == 7

    def test_analyze_performance(self):
        from core.ai.self_improver import SelfImprover
        from core.ai.experience import ExperienceAccumulator
        improver = SelfImprover()
        improver._experience = ExperienceAccumulator(tempfile.mktemp(suffix=".db"))

        result = improver.analyze_performance()
        assert "knowledge" in result
        assert "recommendation" in result

    def test_get_adjusted_parameters(self):
        from core.ai.self_improver import SelfImprover
        from core.ai.experience import ExperienceAccumulator
        improver = SelfImprover()
        improver._experience = ExperienceAccumulator(tempfile.mktemp(suffix=".db"))

        result = improver.get_adjusted_parameters("pricing")
        assert result["engine"] == "pricing"
        assert "adjustments" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
