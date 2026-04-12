"""Revenue Strategy — AI plan to generate first sales and grow revenue.

Division of labor (see ``strategy_planner.py`` for the
full picture):

  * ``strategy_planner.py`` — **memory-driven**.
  * ``strategy_expander.py`` — **coverage-driven**.
  * ``revenue_strategy.py`` (this file) — **state-driven**.
    Picks actionable plays based on the store's CURRENT
    phase (launch / growth / scale) from raw products +
    orders + customers. Does NOT consult accumulated memory
    or rule history — those are the planner's job. Runs
    every cycle as part of the fast plan phase.

Analyzes store state and creates actionable revenue plan:
  1. SEO optimization (title, description, tags)
  2. Social media strategy
  3. Discount strategy for first customers
  4. Content marketing plan
  5. Product positioning recommendations
"""
from __future__ import annotations
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("strategy.revenue")


class RevenueStrategy:
    """Creates actionable revenue generation plans."""

    def create_plan(self, products: list[dict], orders: list[dict],
                    customers: list[dict]) -> dict[str, Any]:
        """Generate revenue strategy based on current store state."""
        revenue = sum(float(o.get("total_price", o.get("total", 0))) for o in orders)
        has_orders = len(orders) > 0

        plan = {
            "current_revenue": round(revenue, 2),
            "current_orders": len(orders),
            "phase": "launch" if not has_orders else "growth" if revenue < 1000 else "scale",
            "strategies": [],
            "immediate_actions": [],
            "timeline": {},
        }

        if not has_orders:
            plan["strategies"] = self._launch_strategy(products)
            plan["immediate_actions"] = self._launch_actions(products)
            plan["timeline"] = {
                "week_1": "SEO + social media + discount codes",
                "week_2": "Content marketing + influencer outreach",
                "week_3": "Paid ads (small budget test)",
                "week_4": "Analyze results, double down on winners",
            }
        elif revenue < 1000:
            plan["strategies"] = self._growth_strategy(products, orders)
            plan["immediate_actions"] = self._growth_actions(products, orders)
        else:
            plan["strategies"] = self._scale_strategy(products, orders, customers)

        # Record
        self._record(plan)
        return plan

    @staticmethod
    def _launch_strategy(products: list) -> list[dict]:
        strategies = []
        strategies.append({
            "name": "seo_foundation",
            "priority": "critical",
            "description": "Optimize all product titles and descriptions for search",
            "expected_impact": "Organic traffic in 2-4 weeks",
            "effort": "low",
        })
        strategies.append({
            "name": "social_proof",
            "priority": "high",
            "description": "Create social media presence (Instagram, TikTok, Pinterest)",
            "expected_impact": "Brand awareness + direct traffic",
            "effort": "medium",
        })
        strategies.append({
            "name": "launch_discounts",
            "priority": "high",
            "description": "Aggressive first-buyer discounts (15-20% off)",
            "expected_impact": "Convert first visitors to buyers",
            "effort": "low",
        })
        strategies.append({
            "name": "content_marketing",
            "priority": "medium",
            "description": "Blog posts, buying guides, product comparisons",
            "expected_impact": "SEO + authority building",
            "effort": "medium",
        })
        if len(products) < 20:
            strategies.append({
                "name": "expand_catalog",
                "priority": "medium",
                "description": "Add more products to increase selection (target 30+)",
                "expected_impact": "More keywords, more traffic, more sales",
                "effort": "medium",
            })
        return strategies

    @staticmethod
    def _launch_actions(products: list) -> list[str]:
        actions = [
            "Share store link on 3 social media platforms today",
            "Send WELCOME15 discount code to 10 potential customers",
            "Write 2 blog posts about top products",
            "Submit sitemap to Google Search Console",
            "Join 3 relevant Facebook groups and share products",
        ]
        avg_price = sum(float(p.get("price", 0)) for p in products) / max(len(products), 1)
        if avg_price > 30:
            actions.append("Consider lowering entry price to under $20 for first product")
        return actions

    @staticmethod
    def _growth_strategy(products: list, orders: list) -> list[dict]:
        return [
            {"name": "repeat_buyers", "priority": "critical",
             "description": "Email marketing to convert one-time to repeat buyers"},
            {"name": "upsell_cross_sell", "priority": "high",
             "description": "Recommend related products at checkout"},
            {"name": "paid_ads", "priority": "high",
             "description": "Start Google Shopping + Facebook retargeting ($5-10/day)"},
        ]

    @staticmethod
    def _growth_actions(products: list, orders: list) -> list[str]:
        return [
            "Set up email welcome sequence (3 emails)",
            "Create 'Customers also bought' section",
            "Start Google Shopping feed",
            "Retarget store visitors on Facebook ($5/day)",
        ]

    @staticmethod
    def _scale_strategy(products: list, orders: list, customers: list) -> list[dict]:
        return [
            {"name": "increase_aov", "priority": "critical",
             "description": "Increase average order value with bundles and upsells"},
            {"name": "expand_channels", "priority": "high",
             "description": "Add Amazon, Etsy, eBay as sales channels"},
            {"name": "loyalty_program", "priority": "medium",
             "description": "Launch loyalty/rewards program for repeat buyers"},
        ]

    @staticmethod
    def _record(plan: dict):
        try:
            from core.data.architecture import get_data_architecture
            da = get_data_architecture()
            da.capture("knowledge", {
                "content": "Revenue plan: {} phase, {} strategies".format(
                    plan["phase"], len(plan["strategies"])),
                "knowledge_type": "strategy",
                "domain": "revenue",
                "confidence": 0.7,
            }, source="revenue_strategy", score=4.0)
        except Exception as exc:
            logger.debug("data-architecture capture failed: %s", exc)

    def get_stats(self) -> dict[str, Any]:
        return {"plans_generated": 1}


_instance = None
def get_revenue_strategy():
    global _instance
    if _instance is None:
        _instance = RevenueStrategy()
    return _instance
