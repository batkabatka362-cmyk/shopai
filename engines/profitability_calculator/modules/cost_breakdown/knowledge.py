"""Domain knowledge for e-commerce cost management.

Hard-won lessons from real stores. Each insight includes context on
when it matters most and what to do about it.
"""

from __future__ import annotations

from typing import Any

COST_KNOWLEDGE: list[dict[str, Any]] = [
    {
        "id": "payment_fees_fixed",
        "insight": "Payment fees are fixed — focus on other costs",
        "detail": (
            "Credit card processing at 2.9% + $0.30 is effectively a tax on revenue. "
            "You cannot negotiate it below ~2.4% unless you process $1M+/month. "
            "Every minute spent trying to shave payment fees is better spent on "
            "shipping, packaging, or supplier negotiations."
        ),
        "applies_when": "always",
        "impact": "low_savings_potential",
        "priority": 5,
    },
    {
        "id": "shipping_margin_killer",
        "insight": "Shipping is the #1 margin killer for products over 3kg",
        "detail": (
            "At 3kg+, shipping jumps from ~$8 to $11-15 domestic. International "
            "doubles or triples that. A $30 product that costs $14 to ship is "
            "dead on arrival. Either build shipping into the price ('free shipping' "
            "at a higher price) or restrict heavy-item sales to domestic only."
        ),
        "applies_when": "product_weight_kg > 3.0",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "packaging_volume_discount",
        "insight": "Packaging cost per unit drops 50% at 1000+ quantity",
        "detail": (
            "Custom boxes at qty 100 cost ~$2 each. At 1000 they drop to $1. "
            "At 5000 they hit $0.60. If you are spending more than 3% of revenue "
            "on packaging, you are either ordering too few or over-packaging. "
            "Standard brown box + tissue paper outperforms fancy packaging in "
            "repeat purchase rate for most non-luxury segments."
        ),
        "applies_when": "monthly_volume < 1000",
        "impact": "medium_savings",
        "priority": 3,
    },
    {
        "id": "returns_true_cost",
        "insight": "Returns cost 3x what you think (shipping + restock + depreciation + customer loss)",
        "detail": (
            "A returned $50 item does not cost $50. It costs: return shipping ($8), "
            "restocking labor ($3), depreciation/damage (15% = $7.50), lost customer "
            "lifetime value (~$25), and payment processing on the refund ($0.30 fee "
            "not refunded). True cost of one return: ~$44. At an 8% return rate, "
            "returns eat 3-5% of gross revenue — not the 1% most sellers budget."
        ),
        "applies_when": "return_rate > 0.05",
        "impact": "critical",
        "priority": 1,
    },
    {
        "id": "shopify_fee_allocation",
        "insight": "Shopify fees matter less as volume grows — do not over-optimize early",
        "detail": (
            "At 50 orders/month, $39 Basic plan = $0.78/order. At 500 orders/month "
            "that drops to $0.08/order. Upgrading to Advanced ($399) only makes sense "
            "above ~400 orders/month when the lower transaction fees offset the higher "
            "subscription. Do not upgrade plans to 'save money' until the math works."
        ),
        "applies_when": "monthly_orders < 500",
        "impact": "low_savings_potential",
        "priority": 4,
    },
    {
        "id": "customs_de_minimis",
        "insight": "Ship orders under $800 to avoid US customs duties entirely",
        "detail": (
            "The US de minimis threshold is $800. Shipments valued below this "
            "enter duty-free. If you import bulk and break into individual orders, "
            "each order is assessed separately. This is why DTC brands importing "
            "from China often ship individual parcels via ePacket rather than "
            "container loads — duty avoidance at scale."
        ),
        "applies_when": "is_imported and product_value < 800",
        "impact": "high_savings",
        "priority": 2,
    },
    {
        "id": "insurance_skip_low_value",
        "insight": "Self-insure items under $50 — insurance premiums exceed claim value",
        "detail": (
            "Shipping insurance at 1.5-3% means $0.75-1.50 on a $50 item. "
            "With a loss rate of ~1%, expected loss is $0.50/unit. Insurance costs "
            "more than the risk. Set aside a self-insurance reserve instead: "
            "take 1% of revenue into a loss reserve fund and skip the premium."
        ),
        "applies_when": "product_value < 50",
        "impact": "small_savings",
        "priority": 4,
    },
    {
        "id": "warehouse_turnover",
        "insight": "Slow inventory kills margins silently — 90 day stock = double storage cost",
        "detail": (
            "At $0.75/cuft/month, a product taking 1 cuft with 45-day turnover "
            "costs $1.12 in storage. At 90-day turnover that doubles to $2.25. "
            "Worse, Amazon FBA charges long-term storage surcharges after 180 days. "
            "Fast inventory turnover is a hidden profit lever most sellers ignore."
        ),
        "applies_when": "inventory_turnover_days > 60",
        "impact": "medium_savings",
        "priority": 2,
    },
    {
        "id": "free_shipping_psychology",
        "insight": "Free shipping converts 20-30% better — bake it into the price",
        "detail": (
            "A $35 product with $8 shipping converts worse than a $43 product "
            "with free shipping — even though the customer pays the same. "
            "Absorb shipping into the price. Your cost per unit stays identical "
            "but conversion rate jumps. The math always favors 'free' shipping "
            "above $25 price points."
        ),
        "applies_when": "selling_price > 25",
        "impact": "revenue_increase",
        "priority": 2,
    },
    {
        "id": "cac_benchmark",
        "insight": "If CAC exceeds 25% of first-order revenue, you need repeat purchases to survive",
        "detail": (
            "Healthy CAC for e-commerce is 10-20% of AOV. At 25%+, first-order "
            "profit is near zero or negative. The business only works if customers "
            "reorder 2-3 times. Consumables and subscriptions can tolerate high CAC. "
            "One-time purchases (furniture, electronics) cannot."
        ),
        "applies_when": "cac_ratio > 0.20",
        "impact": "critical",
        "priority": 1,
    },
]


def get_cost_insight(insight_id: str) -> dict[str, Any] | None:
    """Retrieve a specific knowledge entry by ID."""
    for entry in COST_KNOWLEDGE:
        if entry["id"] == insight_id:
            return entry
    return None


def get_relevant_insights(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return insights relevant to a given product/order context.

    Args:
        context: dict with keys like product_weight_kg, product_value,
                 monthly_volume, return_rate, is_imported, selling_price, etc.

    Returns:
        List of matching knowledge entries sorted by priority (1 = highest).
    """
    relevant: list[dict[str, Any]] = []

    weight = context.get("product_weight_kg", 0)
    value = context.get("product_value", 0)
    volume = context.get("monthly_volume", 0)
    return_rate = context.get("return_rate", 0.08)
    is_imported = context.get("is_imported", False)
    selling_price = context.get("selling_price", 0)
    turnover_days = context.get("inventory_turnover_days", 45)
    cac_ratio = context.get("cac_ratio", 0)

    for entry in COST_KNOWLEDGE:
        condition = entry["applies_when"]
        match = False

        if condition == "always":
            match = True
        elif "product_weight_kg > 3.0" in condition and weight > 3.0:
            match = True
        elif "monthly_volume < 1000" in condition and volume < 1000:
            match = True
        elif "return_rate > 0.05" in condition and return_rate > 0.05:
            match = True
        elif "monthly_orders < 500" in condition and volume < 500:
            match = True
        elif "is_imported" in condition and is_imported:
            match = True
        elif "product_value < 50" in condition and value < 50:
            match = True
        elif "inventory_turnover_days > 60" in condition and turnover_days > 60:
            match = True
        elif "selling_price > 25" in condition and selling_price > 25:
            match = True
        elif "cac_ratio > 0.20" in condition and cac_ratio > 0.20:
            match = True

        if match:
            relevant.append(entry)

    relevant.sort(key=lambda x: x["priority"])
    return relevant
