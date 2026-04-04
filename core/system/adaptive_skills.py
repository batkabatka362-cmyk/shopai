"""AdaptiveSkills — AI learns which approaches work best and adapts.

Skills are strategies the AI can choose from. Each skill:
  - Has a success score (updated after every use)
  - Has conditions (when to use it)
  - Can be combined with other skills

The AI picks the best skill for each situation based on past results.
Over time, it learns which skills work for which conditions.
"""
from __future__ import annotations

import json
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("adaptive_skills")


class Skill:
    """A single adaptive skill."""

    def __init__(self, name: str, category: str, description: str,
                 conditions: dict | None = None) -> None:
        self.name = name
        self.category = category
        self.description = description
        self.conditions = conditions or {}
        self.score = 0.5  # Start neutral
        self.uses = 0
        self.successes = 0
        self.last_used = 0.0
        self.created_at = time.time()

    def record_use(self, success: bool, impact: float = 0) -> None:
        self.uses += 1
        if success:
            self.successes += 1
        self.last_used = time.time()
        # Bayesian-like score update
        self.score = (self.score * (self.uses - 1) + (1.0 if success else 0.0)) / self.uses
        # Boost by impact
        if impact > 0:
            self.score = min(1.0, self.score + impact * 0.05)

    @property
    def success_rate(self) -> float:
        return self.successes / self.uses if self.uses > 0 else 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "category": self.category,
            "description": self.description, "score": round(self.score, 3),
            "uses": self.uses, "success_rate": round(self.success_rate, 3),
            "conditions": self.conditions,
        }


class AdaptiveSkills:
    """Manages and evolves AI skills based on outcomes."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._init_default_skills()

    def _init_default_skills(self) -> None:
        """Initialize built-in skills."""
        defaults = [
            # Pricing skills
            ("competitive_pricing", "pricing", "Match or undercut competitor prices",
             {"when": "high_competition"}),
            ("premium_pricing", "pricing", "Price higher with strong branding",
             {"when": "unique_product"}),
            ("psychological_pricing", "pricing", "Use $X.99 endings",
             {"when": "always"}),
            ("bundle_pricing", "pricing", "Offer discounts for buying multiple",
             {"when": "complementary_products"}),
            ("dynamic_pricing", "pricing", "Adjust price based on demand/stock",
             {"when": "variable_demand"}),

            # Product skills
            ("trending_product_hunt", "product", "Find trending products via search data",
             {"when": "need_new_products"}),
            ("competitor_spy", "product", "Find what competitors sell successfully",
             {"when": "need_product_ideas"}),
            ("niche_deep_dive", "product", "Deep research into specific niche",
             {"when": "expanding_niche"}),
            ("cross_sell_finder", "product", "Find products that complement existing catalog",
             {"when": "have_products"}),

            # Marketing skills
            ("urgency_creation", "marketing", "Create urgency with limited time/stock messaging",
             {"when": "slow_sales"}),
            ("social_proof", "marketing", "Use reviews, testimonials, user-generated content",
             {"when": "have_reviews"}),
            ("email_sequence", "marketing", "Automated email drip campaigns",
             {"when": "have_customers"}),
            ("retargeting", "marketing", "Re-target visitors who didn't buy",
             {"when": "have_traffic"}),

            # Content skills
            ("seo_title_optimization", "content", "Optimize product titles for search",
             {"when": "always"}),
            ("benefit_focused_copy", "content", "Write descriptions focused on benefits not features",
             {"when": "always"}),
            ("ai_product_description", "content", "Use LLM to generate compelling descriptions",
             {"when": "have_llm"}),

            # Operations skills
            ("stock_prediction", "operations", "Predict when to reorder based on velocity",
             {"when": "have_sales_data"}),
            ("supplier_diversification", "operations", "Use multiple suppliers to reduce risk",
             {"when": "single_supplier"}),
            ("shipping_optimization", "operations", "Optimize shipping methods and costs",
             {"when": "have_orders"}),

            # Customer skills
            ("vip_program", "customer", "Create loyalty/VIP program for top customers",
             {"when": "have_repeat_buyers"}),
            ("win_back_campaign", "customer", "Re-engage customers who stopped buying",
             {"when": "have_churned_customers"}),
            ("personalization", "customer", "Personalize recommendations per customer",
             {"when": "have_customer_data"}),
        ]

        for name, cat, desc, conditions in defaults:
            self._skills[name] = Skill(name, cat, desc, conditions)

    # ── Skill Selection ──────────────────────────────────────

    def get_best_skills(self, category: str, context: dict | None = None,
                        limit: int = 3) -> list[Skill]:
        """Get the best skills for a category based on past performance."""
        candidates = [s for s in self._skills.values() if s.category == category]

        # Filter by conditions if context provided
        if context:
            filtered = []
            for skill in candidates:
                condition = skill.conditions.get("when", "always")
                if condition == "always" or self._condition_met(condition, context):
                    filtered.append(skill)
            candidates = filtered or candidates

        # Sort by score (best first)
        candidates.sort(key=lambda s: s.score, reverse=True)
        return candidates[:limit]

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def recommend_skills(self, store_state: dict[str, Any]) -> list[dict[str, Any]]:
        """Recommend skills based on current store state."""
        recommendations = []

        products = store_state.get("products", [])
        orders = store_state.get("orders", [])
        customers = store_state.get("customers", [])

        context = {
            "have_products": len(products) > 0,
            "need_new_products": len(products) < 10,
            "have_sales_data": len(orders) > 0,
            "have_customers": len(customers) > 0,
            "have_repeat_buyers": any(c.get("orders", 0) > 1 for c in customers),
            "slow_sales": len(orders) < 5,
            "high_competition": True,  # Default assumption
        }

        # Get best skills per category
        for category in ["pricing", "product", "marketing", "content", "operations", "customer"]:
            best = self.get_best_skills(category, context, limit=2)
            for skill in best:
                recommendations.append({
                    **skill.to_dict(),
                    "reason": f"Best {category} strategy (score: {skill.score:.2f})",
                })

        return recommendations

    # ── Learning ─────────────────────────────────────────────

    def record_outcome(self, skill_name: str, success: bool, impact: float = 0) -> None:
        """Record the outcome of using a skill."""
        skill = self._skills.get(skill_name)
        if skill:
            skill.record_use(success, impact)
            logger.info("Skill %s: %s (score: %.3f after %d uses)",
                       skill_name, "success" if success else "fail", skill.score, skill.uses)

    def add_skill(self, name: str, category: str, description: str,
                  conditions: dict | None = None) -> Skill:
        """Add a new learned skill."""
        skill = Skill(name, category, description, conditions)
        self._skills[name] = skill
        return skill

    # ── Analysis ─────────────────────────────────────────────

    def get_all_skills(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in sorted(self._skills.values(),
                key=lambda s: s.score, reverse=True)]

    def get_category_summary(self) -> dict[str, Any]:
        categories: dict[str, list] = {}
        for skill in self._skills.values():
            categories.setdefault(skill.category, []).append(skill)

        summary = {}
        for cat, skills in categories.items():
            best = max(skills, key=lambda s: s.score)
            summary[cat] = {
                "total_skills": len(skills),
                "best_skill": best.name,
                "best_score": round(best.score, 3),
                "total_uses": sum(s.uses for s in skills),
            }
        return summary

    def get_underperformers(self, min_uses: int = 3) -> list[dict[str, Any]]:
        """Find skills that consistently fail."""
        return [s.to_dict() for s in self._skills.values()
                if s.uses >= min_uses and s.score < 0.3]

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _condition_met(condition: str, context: dict) -> bool:
        return context.get(condition, False)


# Singleton
_skills: AdaptiveSkills | None = None


def get_adaptive_skills() -> AdaptiveSkills:
    global _skills
    if _skills is None:
        _skills = AdaptiveSkills()
    return _skills
