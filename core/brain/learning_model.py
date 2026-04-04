"""LearningModel — the 4th model dedicated to intelligence growth.

This model NEVER executes actions. It only:
  - Analyzes aggregated historical data
  - Finds patterns across all decisions
  - Generates rules for the decision engine
  - Runs simulations to test strategies
  - Improves the entire system

Runs in PARALLEL with worker models. Never blocks execution.
Uses HISTORICAL data (not live data).
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.learning_model")


class LearningModel:
    """Dedicated intelligence model — analyzes, learns, improves."""

    def __init__(self) -> None:
        self._memory = None
        self._llm = None

    def _init(self) -> None:
        if not self._memory:
            from core.brain.memory import get_brain_memory
            self._memory = get_brain_memory()
        if not self._llm:
            try:
                from core.system.llm_adapter import get_llm
                self._llm = get_llm()
            except Exception:
                pass

    # ── Phase 1: Data Analysis ───────────────────────────────

    def analyze_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze historical data for intelligence."""
        self._init()

        products = data.get("products", [])
        orders = data.get("orders", data.get("order_data", []))
        customers = data.get("customers", data.get("customer_data", []))

        analysis: dict[str, Any] = {"timestamp": time.time()}

        # Product analysis
        if products:
            prices = [float(p.get("price", 0) or 0) for p in products if p.get("price")]
            costs = [float(p.get("cost", 0) or 0) for p in products if p.get("cost")]
            margins = [(p - c) / p for p, c in zip(prices, costs) if p > 0 and c > 0]

            analysis["products"] = {
                "count": len(products),
                "avg_price": round(sum(prices) / len(prices), 2) if prices else 0,
                "avg_cost": round(sum(costs) / len(costs), 2) if costs else 0,
                "avg_margin": round(sum(margins) / len(margins), 3) if margins else 0,
                "price_range": {"min": min(prices) if prices else 0, "max": max(prices) if prices else 0},
                "no_images": sum(1 for p in products if not p.get("image_url")),
                "no_cost": sum(1 for p in products if not p.get("cost")),
            }

        # Order analysis
        if orders:
            totals = [float(o.get("total", 0) or 0) for o in orders]
            analysis["orders"] = {
                "count": len(orders),
                "total_revenue": round(sum(totals), 2),
                "avg_order_value": round(sum(totals) / len(totals), 2) if totals else 0,
            }
        else:
            analysis["orders"] = {"count": 0, "total_revenue": 0, "critical": "NO SALES — top priority"}

        # Customer analysis
        if customers:
            repeat = sum(1 for c in customers if int(c.get("orders", c.get("orders_count", 0)) or 0) > 1)
            analysis["customers"] = {
                "count": len(customers),
                "repeat_buyers": repeat,
                "repeat_rate": round(repeat / len(customers), 2) if customers else 0,
            }

        # Score overall store health
        health = 50
        if analysis.get("products", {}).get("count", 0) >= 10:
            health += 10
        if analysis.get("products", {}).get("avg_margin", 0) > 0.5:
            health += 10
        if analysis.get("orders", {}).get("count", 0) > 0:
            health += 15
        if analysis.get("products", {}).get("no_images", 0) == 0:
            health += 10
        analysis["health_score"] = min(100, health)

        return analysis

    # ── Phase 2: Pattern Detection ───────────────────────────

    def find_patterns(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Find patterns in historical data."""
        self._init()
        patterns = []

        products = data.get("products", [])

        # Pattern: price tier vs margin
        tiers: dict[str, list] = {"budget": [], "mid": [], "premium": []}
        for p in products:
            price = float(p.get("price", 0) or 0)
            cost = float(p.get("cost", 0) or 0)
            if price > 0 and cost > 0:
                margin = (price - cost) / price
                tier = "premium" if price > 40 else "mid" if price > 20 else "budget"
                tiers[tier].append(margin)

        for tier, margins in tiers.items():
            if margins:
                avg = sum(margins) / len(margins)
                patterns.append({
                    "type": "price_tier_margin",
                    "pattern": f"{tier} products: avg margin {avg:.0%}",
                    "tier": tier,
                    "avg_margin": round(avg, 3),
                    "count": len(margins),
                    "significance": "high" if len(margins) >= 3 else "low",
                })

        # Pattern: category distribution
        categories: dict[str, int] = {}
        for p in products:
            cat = p.get("category", p.get("product_type", "unknown"))
            categories[cat] = categories.get(cat, 0) + 1

        if categories:
            dominant = max(categories.items(), key=lambda x: x[1])
            if dominant[1] > len(products) * 0.5:
                patterns.append({
                    "type": "category_concentration",
                    "pattern": f"Over-concentrated in '{dominant[0]}' ({dominant[1]}/{len(products)})",
                    "category": dominant[0],
                    "risk": "diversification_needed",
                    "significance": "medium",
                })

        # Pattern: inventory distribution
        inv_levels = [int(p.get("inventory_quantity", 0) or 0) for p in products]
        if inv_levels:
            low_stock = sum(1 for i in inv_levels if 0 < i < 10)
            if low_stock > 0:
                patterns.append({
                    "type": "inventory_risk",
                    "pattern": f"{low_stock} products with low stock (<10 units)",
                    "count": low_stock,
                    "significance": "high" if low_stock >= 3 else "medium",
                })

        # Pattern from memory (past decisions)
        if self._memory:
            mem_stats = self._memory.get_stats()
            if mem_stats.get("patterns", 0) > 0:
                patterns.append({
                    "type": "memory_patterns",
                    "pattern": f"{mem_stats['patterns']} patterns detected from {mem_stats['total_memories']} memories",
                    "rules_generated": mem_stats.get("rules", 0),
                    "significance": "high",
                })

        return patterns

    # ── Phase 3: Rule Generation ─────────────────────────────

    def generate_rules(self, patterns: list[dict]) -> list[dict[str, Any]]:
        """Convert patterns into actionable rules."""
        rules = []

        for pattern in patterns:
            ptype = pattern.get("type", "")

            if ptype == "price_tier_margin":
                tier = pattern.get("tier", "")
                margin = pattern.get("avg_margin", 0)
                if margin > 0.6:
                    rules.append({
                        "rule": f"KEEP {tier} pricing — margins strong at {margin:.0%}",
                        "category": "pricing",
                        "action": "keep",
                        "confidence": min(0.9, margin),
                    })
                elif margin < 0.3:
                    rules.append({
                        "rule": f"RAISE {tier} prices — margins too low at {margin:.0%}",
                        "category": "pricing",
                        "action": "raise",
                        "confidence": 0.8,
                    })

            elif ptype == "category_concentration":
                rules.append({
                    "rule": f"DIVERSIFY — too concentrated in {pattern.get('category', '?')}",
                    "category": "product",
                    "action": "diversify",
                    "confidence": 0.7,
                })

            elif ptype == "inventory_risk":
                rules.append({
                    "rule": f"RESTOCK — {pattern.get('count', 0)} products at risk of stockout",
                    "category": "inventory",
                    "action": "restock",
                    "confidence": 0.85,
                })

        # Store rules in memory
        if self._memory and rules:
            for rule in rules:
                self._memory._conn().execute(
                    """INSERT OR IGNORE INTO rules (rule, category, condition, action, confidence, source_pattern, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (rule["rule"], rule["category"], rule.get("rule", ""),
                     rule["action"], rule["confidence"], "learning_model", time.time()),
                )
            self._memory._conn().commit()

        return rules

    # ── Phase 4: Strategy Simulation ─────────────────────────

    def simulate_strategies(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Test strategies without affecting real store."""
        products = data.get("products", [])
        if not products:
            return []

        simulations = []

        # Sim 1: What if we raise all prices 10%?
        current_revenue = sum(float(p.get("price", 0) or 0) for p in products)
        raised_revenue = current_revenue * 1.1
        current_profit = sum(
            float(p.get("price", 0) or 0) - float(p.get("cost", 0) or 0)
            for p in products if float(p.get("cost", 0) or 0) > 0
        )
        raised_profit = sum(
            float(p.get("price", 0) or 0) * 1.1 - float(p.get("cost", 0) or 0)
            for p in products if float(p.get("cost", 0) or 0) > 0
        )
        # Assume 10% price increase → 15% volume decrease
        simulations.append({
            "name": "raise_all_10pct",
            "description": "Raise all prices 10%, expect 15% volume drop",
            "projected_revenue_change": round((raised_revenue * 0.85 - current_revenue) / current_revenue * 100, 1),
            "projected_profit_change": round((raised_profit * 0.85 - current_profit) / current_profit * 100, 1) if current_profit > 0 else 0,
            "risk": "medium",
            "recommendation": "test_on_2_products_first",
        })

        # Sim 2: What if we lower prices 10%?
        lowered_profit = sum(
            float(p.get("price", 0) or 0) * 0.9 - float(p.get("cost", 0) or 0)
            for p in products if float(p.get("cost", 0) or 0) > 0
        )
        simulations.append({
            "name": "lower_all_10pct",
            "description": "Lower all prices 10%, expect 20% volume increase",
            "projected_revenue_change": round((current_revenue * 0.9 * 1.2 - current_revenue) / current_revenue * 100, 1),
            "projected_profit_change": round((lowered_profit * 1.2 - current_profit) / current_profit * 100, 1) if current_profit > 0 else 0,
            "risk": "high",
            "recommendation": "avoid_without_competitor_data",
        })

        # Sim 3: Focus on top 5 margin products only
        sorted_by_margin = sorted(products,
            key=lambda p: (float(p.get("price", 0) or 0) - float(p.get("cost", 0) or 0)) / max(float(p.get("price", 0) or 0), 1),
            reverse=True)
        top5 = sorted_by_margin[:5]
        top5_names = [p.get("name", "?")[:25] for p in top5]
        simulations.append({
            "name": "focus_top5_margin",
            "description": f"Promote top 5 margin products: {', '.join(top5_names[:3])}...",
            "risk": "low",
            "recommendation": "implement_now",
        })

        return simulations
