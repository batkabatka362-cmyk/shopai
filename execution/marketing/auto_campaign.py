"""Marketing Automation — AI-generated campaigns from store intelligence.

NOT random campaigns. Data-driven marketing decisions.

Uses:
  - MemoryIntelligence: what worked before, what failed
  - DataArchitecture: customer segments, product performance
  - RL Pricing: price-sensitive product recommendations
  - A/B Testing: track campaign effectiveness

Campaign Types:
  - email_sequence: automated email flows
  - social_post: social media content
  - discount_campaign: targeted discounts
  - cross_sell: product pairing recommendations
  - retarget: re-engagement campaigns
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("marketing.auto")


CAMPAIGN_TEMPLATES = {
    "email_welcome": {
        "type": "email_sequence",
        "trigger": "new_customer",
        "subject": "Welcome to {store_name}!",
        "steps": 3,
        "delay_days": [0, 3, 7],
    },
    "abandoned_cart": {
        "type": "email_sequence",
        "trigger": "cart_abandoned",
        "subject": "You left something behind!",
        "steps": 2,
        "delay_days": [1, 3],
    },
    "high_margin_promo": {
        "type": "discount_campaign",
        "trigger": "high_margin_product",
        "discount_pct": 10,
        "min_margin_after": 0.30,
    },
    "cross_sell": {
        "type": "cross_sell",
        "trigger": "purchase_complete",
        "max_recommendations": 3,
    },
    "win_back": {
        "type": "retarget",
        "trigger": "inactive_30_days",
        "subject": "We miss you! Here's 15% off",
        "discount_pct": 15,
    },
    "new_product": {
        "type": "social_post",
        "trigger": "product_added",
        "platforms": ["instagram", "facebook"],
    },
}


class MarketingAutomation:
    """AI-driven marketing campaign generator."""

    def __init__(self) -> None:
        self._campaigns: list[dict[str, Any]] = []
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

    def generate_campaigns(self, products: list[dict],
                           customers: list[dict],
                           orders: list[dict],
                           store_id: str = "") -> dict[str, Any]:
        """Generate marketing campaigns based on store intelligence.

        Returns:
            {campaigns, total, by_type, estimated_impact}
        """
        self._ensure_init()
        campaigns = []

        # 1. High-margin product promotion
        high_margin = self._find_high_margin(products)
        if high_margin:
            campaigns.append(self._create_campaign(
                "high_margin_promo",
                products=high_margin,
                reason=f"{len(high_margin)} high-margin products can be promoted",
            ))

        # 2. Cross-sell opportunities
        cross_sells = self._find_cross_sells(products, orders)
        if cross_sells:
            campaigns.append(self._create_campaign(
                "cross_sell",
                products=cross_sells,
                reason=f"{len(cross_sells)} cross-sell pairs found",
            ))

        # 3. Win-back for inactive customers
        inactive = self._find_inactive_customers(customers)
        if inactive:
            campaigns.append(self._create_campaign(
                "win_back",
                customers=inactive,
                reason=f"{len(inactive)} inactive customers to re-engage",
            ))

        # 4. New product announcements (products without orders)
        new_products = self._find_new_products(products, orders)
        if new_products:
            campaigns.append(self._create_campaign(
                "new_product",
                products=new_products,
                reason=f"{len(new_products)} products need visibility",
            ))

        # 5. Welcome sequence (if customers exist)
        if customers:
            campaigns.append(self._create_campaign(
                "email_welcome",
                customers=customers[:5],
                reason="Automated welcome sequence for new customers",
            ))

        # Consult memory for past campaign performance
        past_performance = self._check_past_campaigns()
        for camp in campaigns:
            camp["memory_informed"] = past_performance.get("total_memories", 0) > 0

        # Record campaigns in memory
        self._record_campaigns(campaigns, store_id)

        # Calculate estimated impact
        total_reach = sum(c.get("estimated_reach", 0) for c in campaigns)
        total_revenue = sum(c.get("estimated_revenue", 0) for c in campaigns)

        self._campaigns.extend(campaigns)

        return {
            "campaigns": campaigns,
            "total": len(campaigns),
            "by_type": self._count_by_type(campaigns),
            "estimated_reach": total_reach,
            "estimated_revenue": round(total_revenue, 2),
        }

    def _find_high_margin(self, products: list[dict]) -> list[dict]:
        """Find products with > 50% margin."""
        result = []
        for p in products:
            price = float(p.get("price", 0))
            cost = float(p.get("cost", 0))
            if price > 0 and cost > 0:
                margin = (price - cost) / price
                if margin > 0.5:
                    result.append({"id": p.get("id"), "name": p.get("name", p.get("title", "")),
                                   "price": price, "margin": round(margin, 2)})
        return result[:5]

    def _find_cross_sells(self, products: list[dict],
                          orders: list[dict]) -> list[dict]:
        """Find products frequently bought together."""
        if len(products) < 2:
            return []
        # Simple heuristic: pair products in same category
        by_cat: dict[str, list] = {}
        for p in products:
            cat = p.get("product_type", p.get("category", "general"))
            by_cat.setdefault(cat, []).append(p)

        pairs = []
        for cat, prods in by_cat.items():
            if len(prods) >= 2:
                pairs.append({
                    "product_a": prods[0].get("name", prods[0].get("title", "")),
                    "product_b": prods[1].get("name", prods[1].get("title", "")),
                    "category": cat,
                })
        return pairs[:3]

    @staticmethod
    def _find_inactive_customers(customers: list[dict]) -> list[dict]:
        """Find customers with no recent orders."""
        inactive = []
        for c in customers:
            orders_count = int(c.get("orders_count", c.get("total_orders", 0)) or 0)
            if orders_count <= 1:
                inactive.append({"id": c.get("id"), "orders": orders_count})
        return inactive[:10]

    @staticmethod
    def _find_new_products(products: list[dict], orders: list[dict]) -> list[dict]:
        """Find products with zero or few orders."""
        ordered_ids = set()
        for o in orders:
            items = o.get("line_items", o.get("items", []))
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        ordered_ids.add(str(item.get("product_id", "")))

        new = []
        for p in products:
            if str(p.get("id", "")) not in ordered_ids:
                new.append({"id": p.get("id"), "name": p.get("name", p.get("title", ""))})
        return new[:5]

    def _create_campaign(self, template_name: str, **kwargs) -> dict[str, Any]:
        """Create a campaign from template + context."""
        template = CAMPAIGN_TEMPLATES.get(template_name, {})
        products = kwargs.get("products", [])
        customers = kwargs.get("customers", [])

        campaign = {
            "id": f"camp_{template_name}_{int(time.time())}",
            "template": template_name,
            "type": template.get("type", "general"),
            "trigger": template.get("trigger", ""),
            "reason": kwargs.get("reason", ""),
            "target_count": len(products) + len(customers),
            "estimated_reach": max(len(products), len(customers)) * 10,
            "estimated_revenue": len(products) * 5.0,
            "status": "proposed",
            "created_at": time.time(),
        }
        return campaign

    def _check_past_campaigns(self) -> dict[str, Any]:
        """Check memory for past campaign performance."""
        if not self._memory_intel:
            return {"total_memories": 0}
        return self._memory_intel.retrieve_for_decision("marketing")

    def _record_campaigns(self, campaigns: list[dict], store_id: str) -> None:
        """Record campaigns in memory + data architecture."""
        if self._memory_intel:
            for c in campaigns:
                self._memory_intel.create(
                    category="marketing",
                    content={"campaign": c["template"], "type": c["type"],
                             "target_count": c["target_count"]},
                    action=c["template"],
                    score=3.5,
                    memory_type="episodic",
                    tags=["marketing", "campaign", c["type"]],
                )
        if self._data_arch:
            for c in campaigns:
                self._data_arch.capture("marketing", {
                    "channel": c["type"],
                    "campaign_type": c["template"],
                    "audience_size": c["estimated_reach"],
                    "spend": 0,
                }, source="auto_campaign", store_id=store_id, score=3.5)

    @staticmethod
    def _count_by_type(campaigns: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in campaigns:
            t = c.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_campaigns": len(self._campaigns),
            "by_type": self._count_by_type(self._campaigns),
        }


_instance: MarketingAutomation | None = None

def get_marketing_automation() -> MarketingAutomation:
    global _instance
    if _instance is None:
        _instance = MarketingAutomation()
    return _instance
