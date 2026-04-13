"""Strategy Engine — high-level strategy selection.

Strategy Engine = system-ийн "тархи". Ямар чиглэл барих,
ямар аргаар ажиллах, ямар алхмууд хийхийг тодорхойлно.

Flow:
  Data → Option Generation → Evaluation → Selection → Execution Plan → Monitoring

Strategy Engine бол engine биш — brain layer.
Decision хийнэ, гэхдээ execution хийхгүй.
"""
from __future__ import annotations

import time
from typing import Any


# Available strategies
STRATEGIES = {
    "growth": {
        "name": "Growth Strategy",
        "description": "Maximize revenue growth through new products and markets",
        "focus": ["product_launch", "market_expansion", "customer_acquisition"],
        "risk": "medium",
        "typical_timeline": "3-6 months",
        "best_when": "Market is growing, competition manageable",
    },
    "cost_optimization": {
        "name": "Cost Optimization",
        "description": "Reduce costs and improve margins on existing products",
        "focus": ["pricing_optimization", "supplier_negotiation", "shipping_optimization"],
        "risk": "low",
        "typical_timeline": "1-3 months",
        "best_when": "Revenue stable, margins declining",
    },
    "market_expansion": {
        "name": "Market Expansion",
        "description": "Enter new markets or categories",
        "focus": ["market_research", "trend_discovery", "international"],
        "risk": "high",
        "typical_timeline": "6-12 months",
        "best_when": "Current market saturated, strong cash position",
    },
    "product_focus": {
        "name": "Product Focus",
        "description": "Deepen into existing products — better quality, more reviews, brand building",
        "focus": ["quality_improvement", "review_collection", "brand_building"],
        "risk": "low",
        "typical_timeline": "3-6 months",
        "best_when": "Products selling but margins or reviews need improvement",
    },
    "survival": {
        "name": "Survival Mode",
        "description": "Cut costs, liquidate slow movers, preserve cash",
        "focus": ["clearance", "cost_cutting", "cash_preservation"],
        "risk": "low",
        "typical_timeline": "1-3 months",
        "best_when": "Cash flow negative, margins critical",
    },
}


class StrategyEngine:
    """High-level strategy selection and monitoring."""

    def select_strategy(
        self,
        store_situation: dict[str, Any],
        profit_data: dict[str, Any] | None = None,
        brain_knowledge: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Select the best strategy based on current situation.

        Returns: {status, data: {selected_strategy, reason, execution_plan, ...}, meta, error}
        """
        # Generate options
        options = self._generate_options(store_situation)

        # Evaluate each option
        scored = self._evaluate_options(options, store_situation, profit_data, brain_knowledge)

        # Select best
        scored.sort(key=lambda o: o["score"], reverse=True)
        best = scored[0]

        # Build execution plan
        plan = self._build_execution_plan(best, store_situation)

        return {
            "status": "success",
            "data": {
                "selected_strategy": best["strategy"],
                "strategy_name": best["name"],
                "reason": best["reason"],
                "score": best["score"],
                "risk_level": best["risk"],
                "expected_timeline": best["timeline"],
                "execution_plan": plan,
                "alternatives": [{"strategy": s["strategy"], "score": s["score"], "reason": s["reason"]} for s in scored[1:3]],
            },
            "meta": {
                "engine": "strategy_engine",
                "options_evaluated": len(scored),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "error": None,
        }

    def _generate_options(self, situation: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate strategy options based on situation."""
        options = []
        for key, strategy in STRATEGIES.items():
            options.append({
                "strategy": key,
                "name": strategy["name"],
                "description": strategy["description"],
                "focus": strategy["focus"],
                "risk": strategy["risk"],
                "timeline": strategy["typical_timeline"],
                "best_when": strategy["best_when"],
            })
        return options

    def _evaluate_options(
        self,
        options: list[dict[str, Any]],
        situation: dict[str, Any],
        profit_data: dict[str, Any] | None,
        brain_knowledge: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Score each strategy option."""
        financial = situation.get("financial", {})
        health_grade = financial.get("health_grade", "B")
        profit_status = ""
        if profit_data:
            profit_status = profit_data.get("status", "")

        scored = []
        for opt in options:
            score = 50  # Base
            reason_parts = []

            # Situation-based scoring
            if opt["strategy"] == "survival" and health_grade in ("D", "F"):
                score = 95
                reason_parts.append("Financial health critical — survival mode required")
            elif opt["strategy"] == "survival":
                score = 20
                reason_parts.append("Finances OK — survival not needed")

            elif opt["strategy"] == "growth" and health_grade in ("A", "B"):
                score = 80
                reason_parts.append("Financial health good — growth possible")
            elif opt["strategy"] == "growth" and health_grade in ("D", "F"):
                score = 20
                reason_parts.append("Finances too weak for growth")

            elif opt["strategy"] == "cost_optimization" and profit_status == "losing":
                score = 85
                reason_parts.append("Currently losing money — cost optimization critical")
            elif opt["strategy"] == "cost_optimization":
                score = 55
                reason_parts.append("Cost optimization always beneficial")

            elif opt["strategy"] == "product_focus":
                score = 60
                reason_parts.append("Product improvement is low-risk, steady return")

            elif opt["strategy"] == "market_expansion" and health_grade in ("A",):
                score = 70
                reason_parts.append("Strong finances support expansion")
            elif opt["strategy"] == "market_expansion":
                score = 35
                reason_parts.append("Expansion requires strong financial base")

            # Brain knowledge adjustment
            if brain_knowledge:
                for entry in brain_knowledge:
                    if entry.get("type") == "category_failure" and opt["strategy"] == "market_expansion":
                        score -= 10
                        reason_parts.append("Past expansion attempts failed")
                    if entry.get("type") == "category_success" and opt["strategy"] == "growth":
                        score += 10
                        reason_parts.append("Past growth initiatives succeeded")

            score = max(0, min(100, score))
            scored.append({
                **opt,
                "score": score,
                "reason": ". ".join(reason_parts) if reason_parts else opt["best_when"],
            })

        return scored

    def _build_execution_plan(self, strategy: dict[str, Any], situation: dict[str, Any]) -> list[dict[str, Any]]:
        """Build step-by-step execution plan for selected strategy."""
        plans = {
            "growth": [
                {"step": 1, "action": "Run Market Research on target categories", "agent": "research_agent", "timeline": "Week 1-2"},
                {"step": 2, "action": "Select top 3 products from research", "agent": "product_agent", "timeline": "Week 2-3"},
                {"step": 3, "action": "Source products and calculate profitability", "agent": "sourcing_agent", "timeline": "Week 3-5"},
                {"step": 4, "action": "Create listings and launch marketing", "agent": "marketing_agent", "timeline": "Week 5-8"},
                {"step": 5, "action": "Monitor and optimize", "agent": "optimization_agent", "timeline": "Week 8+"},
            ],
            "cost_optimization": [
                {"step": 1, "action": "Analyze all product margins", "agent": "financial_agent", "timeline": "Week 1"},
                {"step": 2, "action": "Identify top cost reduction opportunities", "agent": "operations_agent", "timeline": "Week 1-2"},
                {"step": 3, "action": "Negotiate with suppliers", "agent": "sourcing_agent", "timeline": "Week 2-4"},
                {"step": 4, "action": "Optimize pricing for margin improvement", "agent": "pricing_agent", "timeline": "Week 2-3"},
                {"step": 5, "action": "Reduce marketing waste", "agent": "marketing_agent", "timeline": "Week 3-4"},
            ],
            "survival": [
                {"step": 1, "action": "IMMEDIATELY pause unprofitable campaigns", "agent": "marketing_agent", "timeline": "Day 1"},
                {"step": 2, "action": "Clearance sale on dead stock", "agent": "operations_agent", "timeline": "Day 1-3"},
                {"step": 3, "action": "Renegotiate supplier terms", "agent": "sourcing_agent", "timeline": "Week 1"},
                {"step": 4, "action": "Focus on highest-margin products only", "agent": "product_agent", "timeline": "Week 1-2"},
                {"step": 5, "action": "Rebuild with lean operations", "agent": "operations_agent", "timeline": "Week 2-4"},
            ],
        }
        return plans.get(strategy["strategy"], [
            {"step": 1, "action": "Analyze current situation", "agent": "research_agent", "timeline": "Week 1"},
            {"step": 2, "action": "Create improvement plan", "agent": "strategy_agent", "timeline": "Week 1-2"},
            {"step": 3, "action": "Execute and monitor", "agent": "operations_agent", "timeline": "Week 2+"},
        ])
