"""OfferArchitect — the art of structuring offers that convert.

"10% хямдрал" ба "Buy 2 Get 1 Free" яг ижил зүйл — гэхдээ BOGO 2x илүү зарагддаг.
Offer FORMAT мэдэх нь чухал.

Knowledge:
  - BOGO: +300% volume, -50% margin per unit, best for clearing stock
  - % off: Universal, easy to understand, best for broad campaigns
  - $ off: Feels bigger on expensive items ($20 off $100 > 20% off $100 psychologically)
  - Free shipping: +130% conversion, lowest cost to merchant
  - Bundle: +200% AOV, hides individual price, creates unique value
  - Gift with purchase: +150% conversion, increases perceived value
  - Payment splitting: +40% AOV, removes price objection for expensive items
"""
from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.offer_architect")

# Offer types with economics and psychology
OFFER_TYPES = {
    "percentage_off": {
        "display": "{pct}% OFF",
        "psychology": "Universal understanding, easy to calculate savings",
        "best_for": "Broad campaigns, products under $100",
        "avg_conversion_lift": 1.5,
        "avg_aov_impact": -0.15,  # Reduces AOV
        "margin_impact": "Direct % reduction",
        "urgency_potential": "medium",
        "rules": {
            "use_when": "price < $100 OR broad audience OR clearance",
            "avoid_when": "luxury brand OR new product launch",
            "sweet_spots": [10, 15, 20, 25, 30, 40, 50],
        },
    },
    "dollar_off": {
        "display": "${amount} OFF",
        "psychology": "Feels bigger on expensive items ($20 off > 20% off at $100)",
        "best_for": "Products over $100, specific dollar savings",
        "avg_conversion_lift": 1.4,
        "avg_aov_impact": -0.10,
        "margin_impact": "Fixed cost, predictable",
        "urgency_potential": "medium",
        "rules": {
            "use_when": "price > $100 OR average_discount < 15%",
            "avoid_when": "price < $30 (feels insignificant)",
            "sweet_spots": [5, 10, 15, 20, 25, 50],
        },
    },
    "bogo": {
        "display": "Buy {x} Get {y} Free",
        "psychology": "Feels like getting something for free (loss aversion trigger)",
        "best_for": "Clearing inventory, consumables, gifts",
        "avg_conversion_lift": 3.0,
        "avg_aov_impact": 0.80,  # Doubles AOV
        "margin_impact": "-50% per unit but +100% volume",
        "urgency_potential": "high",
        "rules": {
            "use_when": "inventory_high OR consumable_product OR margin > 60%",
            "avoid_when": "margin < 40% OR luxury positioning",
            "variants": ["buy_2_get_1", "buy_1_get_1_50off", "buy_3_get_cheapest_free"],
        },
    },
    "free_shipping": {
        "display": "FREE Shipping",
        "psychology": "Removes #1 cart abandonment reason (unexpected shipping costs)",
        "best_for": "Always-on above threshold, cart abandonment recovery",
        "avg_conversion_lift": 1.3,
        "avg_aov_impact": 0.30,  # Increases AOV to hit threshold
        "margin_impact": "Shipping cost absorbed ($4-12 per order)",
        "urgency_potential": "low",
        "rules": {
            "use_when": "cart_abandonment > 60% OR AOV close to threshold",
            "avoid_when": "heavy/oversized products (high shipping cost)",
            "threshold_formula": "AOV × 1.3 rounded to nearest $5",
        },
    },
    "bundle": {
        "display": "{product_a} + {product_b} for ${bundle_price}",
        "psychology": "Hides individual price, creates unique value proposition",
        "best_for": "Cross-sell, slow movers + fast movers, gift sets",
        "avg_conversion_lift": 2.0,
        "avg_aov_impact": 1.0,  # Doubles AOV
        "margin_impact": "Can maintain margin while appearing discounted",
        "urgency_potential": "medium",
        "rules": {
            "use_when": "complementary_products OR slow_mover + fast_mover",
            "avoid_when": "unrelated products OR customer already buying both",
            "pricing": "Sum of individual prices × 0.80-0.85",
        },
    },
    "gift_with_purchase": {
        "display": "FREE {gift} with purchase over ${threshold}",
        "psychology": "Reciprocity trigger + increases perceived value",
        "best_for": "New product sampling, loyalty, increasing AOV",
        "avg_conversion_lift": 1.5,
        "avg_aov_impact": 0.25,
        "margin_impact": "Gift cost only ($2-10 typically)",
        "urgency_potential": "high",
        "rules": {
            "use_when": "launching_new_product OR loyalty_program OR holiday",
            "avoid_when": "gift_cost > 10% of AOV",
            "gift_ideas": ["sample_size", "branded_accessory", "exclusive_item", "mystery_gift"],
        },
    },
    "payment_splitting": {
        "display": "{installments}× ${amount}/mo",
        "psychology": "Makes expensive items feel affordable (anchoring on small number)",
        "best_for": "Products over $50, reduces price objection",
        "avg_conversion_lift": 1.2,
        "avg_aov_impact": 0.40,
        "margin_impact": "BNPL provider fee (4-6%)",
        "urgency_potential": "low",
        "rules": {
            "use_when": "price > $50 AND target_audience not premium",
            "avoid_when": "price < $30 (installments feel silly)",
            "providers": ["afterpay", "klarna", "affirm", "shop_pay_installments"],
        },
    },
    "tiered_discount": {
        "display": "Buy {x}+ save {pct}%, Buy {y}+ save {pct2}%",
        "psychology": "Encourages buying more to unlock bigger savings",
        "best_for": "B2B, bulk purchases, consumables",
        "avg_conversion_lift": 1.3,
        "avg_aov_impact": 0.60,
        "margin_impact": "Higher volume offsets lower per-unit margin",
        "urgency_potential": "medium",
        "rules": {
            "use_when": "product_is_consumable OR b2b_customers OR high_margin",
            "avoid_when": "single_use_product OR low_inventory",
            "tiers": [{"qty": 2, "discount": 10}, {"qty": 3, "discount": 15}, {"qty": 5, "discount": 25}],
        },
    },
}

# Anchoring strategies
ANCHORING_STRATEGIES = {
    "was_now": {
        "display": "Was ${original} → Now ${sale_price}",
        "rule": "Original price must have been genuinely charged for 30+ days",
        "effectiveness": "high",
        "legal_note": "FTC requires genuine former price — no fake inflation",
    },
    "compare_at": {
        "display": "Compare at ${msrp} | Our price ${price}",
        "rule": "MSRP must be real manufacturer suggested price",
        "effectiveness": "medium",
    },
    "savings_highlight": {
        "display": "You save ${amount} ({pct}% off)",
        "rule": "Show absolute AND percentage savings",
        "effectiveness": "high",
        "note": "Show $ amount for expensive items, % for cheap items",
    },
}

# Urgency calibration
URGENCY_TACTICS = {
    "countdown_timer": {"effectiveness": "high", "overuse_risk": "high", "use_max": "2x per month"},
    "limited_stock": {"effectiveness": "high", "overuse_risk": "critical", "rule": "MUST be truthful"},
    "limited_time": {"effectiveness": "medium", "overuse_risk": "medium", "use_max": "1x per week"},
    "early_bird": {"effectiveness": "medium", "overuse_risk": "low", "use_max": "per product launch"},
    "member_exclusive": {"effectiveness": "medium", "overuse_risk": "low", "rule": "Requires loyalty program"},
}


class OfferArchitect:
    """Designs optimal offer structures based on product and customer context.

    Usage:
        architect = OfferArchitect()
        offer = architect.design_offer(product, goal="clear_inventory")
        comparison = architect.compare_offers(product, ["percentage_off", "bogo", "bundle"])
    """

    def design_offer(
        self,
        product: dict[str, Any],
        goal: str = "maximize_conversion",
        customer_segment: str = "general",
    ) -> dict[str, Any]:
        """Design the optimal offer for a product and goal."""
        price = safe_float(product.get("price", 0))
        cost = safe_float(product.get("cost", 0))
        margin_pct = ((price - cost) / max(price, 0.01)) * 100 if price > 0 else 0
        inventory = product.get("inventory_quantity", 0)
        category = product.get("category", product.get("product_type", "general"))

        # Score each offer type for this context
        scored = []
        for offer_type, config in OFFER_TYPES.items():
            score = self._score_offer(offer_type, config, price, margin_pct, inventory, goal, customer_segment)
            scored.append({
                "type": offer_type,
                "display_format": config["display"],
                "score": score,
                "conversion_lift": f"+{(config['avg_conversion_lift']-1)*100:.0f}%",
                "aov_impact": f"{config['avg_aov_impact']:+.0%}",
                "psychology": config["psychology"],
                "best_for": config["best_for"],
            })

        scored.sort(key=lambda s: s["score"], reverse=True)
        best = scored[0]

        # Generate specific offer parameters
        params = self._generate_params(best["type"], price, margin_pct, goal)

        return {
            "recommended_offer": best["type"],
            "display": self._format_display(best["type"], params, product),
            "parameters": params,
            "score": best["score"],
            "reasoning": best["psychology"],
            "alternatives": scored[1:3],
            "anchoring": self._recommend_anchoring(price, params),
            "urgency": self._recommend_urgency(goal, inventory),
        }

    def compare_offers(
        self,
        product: dict[str, Any],
        offer_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Compare multiple offer formats for the same product."""
        price = safe_float(product.get("price", 0))
        cost = safe_float(product.get("cost", 0))
        if not offer_types:
            offer_types = list(OFFER_TYPES.keys())

        comparisons = []
        for ot in offer_types:
            config = OFFER_TYPES.get(ot)
            if not config:
                continue

            params = self._generate_params(ot, price, (price - cost) / max(price, 0.01) * 100, "maximize_conversion")
            effective_discount = params.get("effective_discount_pct", 0)
            new_margin = ((price * (1 - effective_discount / 100) - cost) / max(price, 0.01)) * 100

            comparisons.append({
                "type": ot,
                "display": self._format_display(ot, params, product),
                "effective_discount": f"{effective_discount:.0f}%",
                "projected_conversion_lift": f"+{(config['avg_conversion_lift']-1)*100:.0f}%",
                "projected_aov_change": f"{config['avg_aov_impact']:+.0%}",
                "new_margin": f"{new_margin:.1f}%",
                "best_for": config["best_for"],
            })

        return {
            "product": product.get("title", product.get("name", "Unknown")),
            "original_price": price,
            "comparisons": comparisons,
        }

    def _score_offer(self, offer_type, config, price, margin, inventory, goal, segment):
        score = 50  # base
        # Goal alignment
        if goal == "clear_inventory" and offer_type in ("bogo", "tiered_discount"):
            score += 20
        elif goal == "maximize_conversion" and offer_type in ("free_shipping", "percentage_off"):
            score += 15
        elif goal == "increase_aov" and offer_type in ("bundle", "tiered_discount", "payment_splitting"):
            score += 20
        elif goal == "acquire_customers" and offer_type in ("percentage_off", "gift_with_purchase"):
            score += 15

        # Price-based suitability
        if price > 100 and offer_type in ("dollar_off", "payment_splitting"):
            score += 10
        elif price < 30 and offer_type in ("free_shipping", "percentage_off"):
            score += 10

        # Margin safety
        if margin < 40 and offer_type == "bogo":
            score -= 30  # Can't afford BOGO with low margin
        if margin > 60:
            score += 10  # More room for discounts

        # Inventory-based
        if inventory > 100 and offer_type in ("bogo", "tiered_discount"):
            score += 15  # Need to move stock
        elif inventory < 20 and offer_type == "bogo":
            score -= 20  # Not enough stock for BOGO

        return max(0, min(100, score))

    def _generate_params(self, offer_type, price, margin, goal):
        if offer_type == "percentage_off":
            pct = 15 if goal == "maximize_conversion" else 25 if goal == "clear_inventory" else 10
            return {"discount_pct": pct, "sale_price": round(price * (1 - pct / 100), 2), "effective_discount_pct": pct}
        elif offer_type == "dollar_off":
            amount = round(price * 0.15 / 5) * 5  # 15% rounded to $5
            return {"amount_off": max(5, amount), "sale_price": round(price - amount, 2), "effective_discount_pct": round(amount / max(price, 1) * 100)}
        elif offer_type == "bogo":
            return {"buy": 2, "get": 1, "effective_discount_pct": 33}
        elif offer_type == "free_shipping":
            threshold = round(price * 1.3 / 5) * 5
            return {"threshold": max(25, threshold), "effective_discount_pct": 0}
        elif offer_type == "bundle":
            bundle_price = round(price * 1.7, 2)  # 2 items at 85% each
            return {"items": 2, "bundle_price": bundle_price, "savings": round(price * 2 - bundle_price, 2), "effective_discount_pct": 15}
        elif offer_type == "payment_splitting":
            installments = 4
            monthly = round(price / installments, 2)
            return {"installments": installments, "monthly": monthly, "effective_discount_pct": 0}
        elif offer_type == "tiered_discount":
            return {"tiers": [{"qty": 2, "pct": 10}, {"qty": 3, "pct": 15}, {"qty": 5, "pct": 25}], "effective_discount_pct": 15}
        elif offer_type == "gift_with_purchase":
            return {"threshold": round(price * 1.2, 2), "gift_cost": 5.0, "effective_discount_pct": 0}
        return {"effective_discount_pct": 0}

    def _format_display(self, offer_type, params, product):
        name = product.get("title", product.get("name", "Product"))
        price = safe_float(product.get("price", 0))
        if offer_type == "percentage_off":
            return f"{params['discount_pct']}% OFF {name} — Now ${params['sale_price']}"
        elif offer_type == "dollar_off":
            return f"${params['amount_off']} OFF {name} — Now ${params['sale_price']}"
        elif offer_type == "bogo":
            return f"Buy {params['buy']} Get {params['get']} FREE on {name}"
        elif offer_type == "free_shipping":
            return f"FREE Shipping on orders over ${params['threshold']}"
        elif offer_type == "bundle":
            return f"Bundle Deal: 2× {name} for ${params['bundle_price']} (save ${params['savings']})"
        elif offer_type == "payment_splitting":
            return f"Pay just ${params['monthly']}/mo for {name} ({params['installments']} payments)"
        elif offer_type == "tiered_discount":
            return f"Buy 2+ {name}: Save 10% | Buy 3+: Save 15% | Buy 5+: Save 25%"
        elif offer_type == "gift_with_purchase":
            return f"FREE gift with {name} purchase over ${params['threshold']}"
        return offer_type

    def _recommend_anchoring(self, price, params):
        discount = params.get("effective_discount_pct", 0)
        if discount > 0:
            return {
                "strategy": "was_now",
                "display": f"Was ${price:.2f} → Now ${price * (1 - discount/100):.2f}",
                "savings": f"You save ${price * discount/100:.2f} ({discount}% off)",
            }
        return {"strategy": "none", "note": "No discount to anchor"}

    def _recommend_urgency(self, goal, inventory):
        if goal == "clear_inventory":
            return {"tactic": "limited_stock", "display": f"Only {inventory} left!", "note": "Must be truthful per FTC"}
        elif goal == "acquire_customers":
            return {"tactic": "limited_time", "display": "Offer ends Sunday!", "note": "Set real expiry"}
        return {"tactic": "none", "note": "No urgency needed for this goal"}
