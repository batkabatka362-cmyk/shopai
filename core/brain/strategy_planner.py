"""Strategy Planner — long-term AI-generated business strategies.

Uses all intelligence systems to build 5 strategy types:
  growth, pricing, retention, efficiency, competitive
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("strategy_planner")


class StrategyPlanner:
    """Long-term strategic planning from accumulated intelligence."""

    def __init__(self) -> None:
        self._strategies: list[dict[str, Any]] = []
        self._memory_intel = None
        self._data_arch = None

    def _ensure_init(self) -> None:
        if not self._memory_intel:
            try:
                from core.memory.intelligence import get_memory_intelligence
                self._memory_intel = get_memory_intelligence()
            except Exception:
                pass
        if not self._data_arch:
            try:
                from core.data.architecture import get_data_architecture
                self._data_arch = get_data_architecture()
            except Exception:
                pass

    def plan(self, products: list[dict], orders: list[dict],
             customers: list[dict], store_id: str = "") -> dict[str, Any]:
        """Generate strategic plan from all available intelligence."""
        self._ensure_init()

        rules = []
        existing = []
        failures = []
        if self._memory_intel:
            rules = self._memory_intel.get_rules()
            existing = self._memory_intel.get_strategies()
            failures = self._memory_intel.analyze_failures()

        analysis = self._analyze_store(products, orders, customers)
        strategies = []

        strategies.append(self._plan_pricing(products, rules, analysis))
        strategies.append(self._plan_growth(products, orders, analysis))
        strategies.append(self._plan_retention(customers, orders, analysis))
        strategies.append(self._plan_efficiency(products, analysis, failures))
        strategies.append(self._plan_competitive(products, analysis))

        strategies = [s for s in strategies if s]
        strategies.sort(key=lambda s: s.get("impact_score", 0), reverse=True)

        self._record_strategies(strategies, store_id)
        self._strategies.extend(strategies)

        return {
            "strategies": strategies,
            "total": len(strategies),
            "priority_order": [s["name"] for s in strategies],
            "intelligence_used": {
                "rules": len(rules),
                "existing_strategies": len(existing),
                "failure_insights": len(failures),
            },
        }

    @staticmethod
    def _analyze_store(products, orders, customers):
        prices = [float(p.get("price", 0)) for p in products if p.get("price")]
        margins = []
        for p in products:
            pr = float(p.get("price", 0))
            co = float(p.get("cost", 0))
            if pr > 0 and co > 0:
                margins.append((pr - co) / pr)
        return {
            "product_count": len(products),
            "order_count": len(orders),
            "customer_count": len(customers),
            "avg_price": round(sum(prices) / max(len(prices), 1), 2),
            "avg_margin": round(sum(margins) / max(len(margins), 1), 3) if margins else 0,
            "high_margin": sum(1 for m in margins if m > 0.5),
            "low_margin": sum(1 for m in margins if m < 0.2),
        }

    def _plan_pricing(self, products, rules, a):
        actions = []
        if a["low_margin"] > 0:
            actions.append("Raise prices on {} low-margin products".format(a["low_margin"]))
        if a["avg_margin"] < 0.3:
            actions.append("Overall margins too low - review cost structure")
        if a["avg_margin"] > 0.6:
            actions.append("High margins - consider competitive pricing for volume")
        for r in [r for r in rules if r.get("category") == "pricing"][:2]:
            rc = r.get("content", {})
            if isinstance(rc, dict):
                actions.append("Rule: {}".format(str(rc.get("rule", ""))[:60]))
        if not actions:
            actions.append("Pricing stable - monitor for changes")
        return {"name": "pricing_optimization", "type": "pricing",
                "description": "Optimize pricing ({} products, {:.0%} avg margin)".format(a["product_count"], a["avg_margin"]),
                "actions": actions, "impact_score": 0.8 if a["avg_margin"] < 0.3 else 0.5, "timeframe": "1-2 weeks"}

    @staticmethod
    def _plan_growth(products, orders, a):
        actions = []
        if a["product_count"] < 20:
            actions.append("Expand catalog from {} to 30+ products".format(a["product_count"]))
        if a["order_count"] == 0:
            actions.append("Priority: get first sales with promotional pricing")
        actions.append("Identify top category and expand")
        return {"name": "catalog_growth", "type": "growth",
                "description": "Grow from {} products".format(a["product_count"]),
                "actions": actions, "impact_score": 0.7 if a["product_count"] < 20 else 0.3, "timeframe": "2-4 weeks"}

    @staticmethod
    def _plan_retention(customers, orders, a):
        actions = []
        if a["customer_count"] > 0:
            repeat = sum(1 for c in customers if int(c.get("orders_count", c.get("total_orders", 0)) or 0) > 1)
            rate = repeat / max(a["customer_count"], 1)
            actions.append("Repeat rate: {:.0%} - target 30%+".format(rate))
            if rate < 0.2:
                actions.append("Launch email welcome + win-back sequences")
        else:
            actions.append("No customers yet - focus on acquisition")
        return {"name": "customer_retention", "type": "retention",
                "description": "Maximize LTV ({} customers)".format(a["customer_count"]),
                "actions": actions, "impact_score": 0.6 if a["customer_count"] > 5 else 0.3, "timeframe": "ongoing"}

    @staticmethod
    def _plan_efficiency(products, a, failures):
        actions = []
        for f in failures[:3]:
            actions.append("Avoid: {} ({} times)".format(f.get("root_cause", "?"), f.get("count", 0)))
        if a["low_margin"] > 3:
            actions.append("Review {} low-margin products".format(a["low_margin"]))
        if not actions:
            actions.append("Operations efficient - monitor")
        return {"name": "operational_efficiency", "type": "efficiency",
                "description": "Reduce costs, improve margins",
                "actions": actions, "impact_score": 0.5, "timeframe": "1-3 weeks"}

    @staticmethod
    def _plan_competitive(products, a):
        return {"name": "market_positioning", "type": "competitive",
                "description": "Position {} products competitively".format(a["product_count"]),
                "actions": ["Monitor competitor prices weekly",
                            "Differentiate on quality/service",
                            "Avg price ${:.2f} - ensure competitive".format(a["avg_price"])],
                "impact_score": 0.4, "timeframe": "ongoing"}

    def _record_strategies(self, strategies, store_id):
        if self._memory_intel:
            for s in strategies:
                self._memory_intel.create(
                    category="strategy", content={"name": s["name"], "type": s["type"],
                    "actions": s["actions"][:3], "impact": s["impact_score"]},
                    action=s["name"], score=3.0 + s["impact_score"],
                    memory_type="semantic", tags=["strategy", s["type"], s["name"]])
        if self._data_arch:
            for s in strategies:
                self._data_arch.capture("knowledge", {
                    "content": "Strategy: {} - {}".format(s["name"], s["description"][:60]),
                    "knowledge_type": "strategy", "domain": s["type"],
                    "confidence": s["impact_score"]},
                    source="strategy_planner", store_id=store_id, score=3.0 + s["impact_score"])

    def get_stats(self):
        types = {}
        for s in self._strategies:
            types[s["type"]] = types.get(s["type"], 0) + 1
        return {"total": len(self._strategies), "by_type": types}


_instance = None

def get_strategy_planner():
    global _instance
    if _instance is None:
        _instance = StrategyPlanner()
    return _instance
