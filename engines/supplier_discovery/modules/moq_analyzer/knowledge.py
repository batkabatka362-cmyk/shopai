"""
Domain knowledge for MOQ negotiation tactics and inventory management formulas.
"""

import math


# ---------------------------------------------------------------------------
# Negotiation tactics catalogue
# ---------------------------------------------------------------------------

NEGOTIATION_TACTICS = [
    {
        "id": "price_premium",
        "name": "Pay higher unit price for lower MOQ",
        "description": (
            "Offer the supplier a 5-20% price premium per unit in exchange for "
            "a reduced minimum order. Suppliers care about total margin; a higher "
            "per-unit price can offset the smaller volume."
        ),
        "typical_moq_reduction_pct": 30,
        "cost_impact": "higher_unit_cost",
    },
    {
        "id": "product_bundling",
        "name": "Combine with other products",
        "description": (
            "Order multiple SKUs from the same factory so the combined quantity "
            "reaches their production threshold. Works best when items share "
            "materials or tooling."
        ),
        "typical_moq_reduction_pct": 50,
        "cost_impact": "neutral",
    },
    {
        "id": "seasonal_timing",
        "name": "Order during the factory low season",
        "description": (
            "Factories are more flexible on MOQ during their slow months "
            "(typically Jan-Feb and Jul-Aug for Chinese manufacturers). "
            "Capacity is available and they want to keep lines running."
        ),
        "typical_moq_reduction_pct": 25,
        "cost_impact": "neutral_to_lower",
    },
    {
        "id": "trade_show_deals",
        "name": "Negotiate at trade shows",
        "description": (
            "Suppliers at Canton Fair, Global Sources, or MAGIC are in deal-making "
            "mode. Face-to-face negotiation yields better MOQ concessions than "
            "online messaging. Budget for travel as part of sourcing cost."
        ),
        "typical_moq_reduction_pct": 35,
        "cost_impact": "travel_cost",
    },
    {
        "id": "tiered_commitment",
        "name": "Commit to a multi-order schedule",
        "description": (
            "Guarantee the supplier 3-4 reorders over 12 months in writing. "
            "The total committed volume meets their annual target, so they accept "
            "a smaller first shipment."
        ),
        "typical_moq_reduction_pct": 40,
        "cost_impact": "contractual_obligation",
    },
    {
        "id": "sample_then_scale",
        "name": "Start with a paid sample run",
        "description": (
            "Pay full tooling/setup fees upfront and order a small sample batch "
            "(50-100 units). Use sales data from that batch to justify a larger "
            "follow-up order."
        ),
        "typical_moq_reduction_pct": 60,
        "cost_impact": "higher_initial_per_unit",
    },
]


def get_negotiation_tactics(max_results=None):
    """Return the full tactics list, optionally truncated."""
    if max_results is None:
        return NEGOTIATION_TACTICS
    return NEGOTIATION_TACTICS[:max_results]


def get_moq_reduction_strategies(reduction_pct):
    """
    Return tactics likely to achieve the requested reduction percentage,
    sorted by typical effectiveness (descending).
    """
    viable = [
        t for t in NEGOTIATION_TACTICS
        if t["typical_moq_reduction_pct"] >= reduction_pct * 0.5
    ]
    viable.sort(key=lambda t: t["typical_moq_reduction_pct"], reverse=True)
    return viable


# ---------------------------------------------------------------------------
# Inventory management formulas
# ---------------------------------------------------------------------------

def calculate_eoq(annual_demand, ordering_cost, annual_holding_cost_per_unit):
    """
    Economic Order Quantity (Wilson formula).

    EOQ = sqrt(2 * D * S / H)
    D = annual demand (units)
    S = fixed cost per order (USD)
    H = annual holding cost per unit (USD)
    """
    if annual_holding_cost_per_unit <= 0 or annual_demand <= 0:
        return 0
    eoq = math.sqrt(2.0 * annual_demand * ordering_cost / annual_holding_cost_per_unit)
    return int(round(eoq))


def calculate_safety_stock(avg_daily_demand, demand_std_dev,
                           lead_time_days, lead_time_std_dev=0,
                           service_level_z=1.65):
    """
    Safety stock formula accounting for variability in both demand and lead time.

    SS = Z * sqrt(LT * sigma_d^2 + d_avg^2 * sigma_lt^2)

    service_level_z defaults to 1.65 (~95% service level).
    """
    variance = (lead_time_days * demand_std_dev ** 2 +
                avg_daily_demand ** 2 * lead_time_std_dev ** 2)
    ss = service_level_z * math.sqrt(variance)
    return int(math.ceil(ss))


def calculate_reorder_point(avg_daily_demand, lead_time_days, safety_stock):
    """Reorder point = average demand during lead time + safety stock."""
    return int(math.ceil(avg_daily_demand * lead_time_days + safety_stock))


def calculate_inventory_turnover(cogs, avg_inventory_value):
    """Inventory turnover ratio = COGS / average inventory value."""
    if avg_inventory_value <= 0:
        return 0.0
    return round(cogs / avg_inventory_value, 2)


def days_of_inventory(turnover_ratio):
    """Days of inventory on hand = 365 / turnover ratio."""
    if turnover_ratio <= 0:
        return float("inf")
    return round(365.0 / turnover_ratio, 1)
