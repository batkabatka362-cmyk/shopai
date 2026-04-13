"""Tests for ShopifyManager and AdaptiveSkills."""
import pytest


class TestShopifyManager:
    def test_init(self):
        from core.system.shopify_manager import ShopifyManager
        mgr = ShopifyManager("test.myshopify.com", "token")
        assert mgr is not None

    def test_configure(self):
        from core.system.shopify_manager import ShopifyManager
        mgr = ShopifyManager()
        mgr.configure("test.myshopify.com", "token123")
        assert mgr._shop == "test.myshopify.com"
        assert mgr._token == "token123"


class TestAdaptiveSkills:
    def test_init(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        all_skills = skills.get_all_skills()
        assert len(all_skills) > 15  # Should have default skills

    def test_get_best_skills(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        best = skills.get_best_skills("pricing")
        assert len(best) > 0
        assert best[0].category == "pricing"

    def test_record_outcome(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        skills.record_outcome("competitive_pricing", True, 0.8)
        skills.record_outcome("competitive_pricing", True, 0.5)
        skills.record_outcome("competitive_pricing", False)
        skill = skills.get_skill("competitive_pricing")
        assert skill.uses == 3
        assert skill.successes == 2

    def test_add_skill(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        skill = skills.add_skill("new_strategy", "pricing", "A new approach")
        assert skill.name == "new_strategy"
        assert skills.get_skill("new_strategy") is not None

    def test_recommend_skills(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        recs = skills.recommend_skills({
            "products": [{"id": 1}],
            "orders": [],
            "customers": [{"orders": 5}],
        })
        assert len(recs) > 0

    def test_category_summary(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        summary = skills.get_category_summary()
        assert "pricing" in summary
        assert "product" in summary
        assert "marketing" in summary

    def test_underperformers_empty(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        # No skills used yet, so no underperformers
        under = skills.get_underperformers()
        assert len(under) == 0

    def test_skill_score_updates(self):
        from core.system.adaptive_skills import AdaptiveSkills
        skills = AdaptiveSkills()
        skill = skills.get_skill("premium_pricing")
        initial = skill.score
        skills.record_outcome("premium_pricing", True, 0.9)
        assert skill.score >= initial

    def test_singleton(self):
        from core.system.adaptive_skills import get_adaptive_skills
        s1 = get_adaptive_skills()
        s2 = get_adaptive_skills()
        assert s1 is s2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
