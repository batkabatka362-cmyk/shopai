"""Reference data for cost analysis and negotiation.

Typical cost structures, volume discount curves, duty rates,
shipping costs, and insurance rates used to estimate true
landed costs and identify negotiation opportunities.
"""
from __future__ import annotations


# --- Cost breakdowns by product type (fraction of quoted price) ---

COST_BREAKDOWNS_BY_TYPE: dict[str, dict[str, float]] = {
    "electronics": {"material": 0.45, "labor": 0.15, "overhead": 0.20, "profit": 0.20},
    "apparel": {"material": 0.30, "labor": 0.25, "overhead": 0.20, "profit": 0.25},
    "home_goods": {"material": 0.40, "labor": 0.20, "overhead": 0.20, "profit": 0.20},
    "beauty": {"material": 0.20, "labor": 0.15, "overhead": 0.25, "profit": 0.40},
    "toys": {"material": 0.35, "labor": 0.20, "overhead": 0.20, "profit": 0.25},
    "jewelry": {"material": 0.50, "labor": 0.15, "overhead": 0.10, "profit": 0.25},
    "furniture": {"material": 0.45, "labor": 0.25, "overhead": 0.15, "profit": 0.15},
    "food_supplement": {"material": 0.25, "labor": 0.10, "overhead": 0.30, "profit": 0.35},
    "sporting_goods": {"material": 0.40, "labor": 0.20, "overhead": 0.20, "profit": 0.20},
    "pet_products": {"material": 0.35, "labor": 0.20, "overhead": 0.20, "profit": 0.25},
    "general": {"material": 0.35, "labor": 0.20, "overhead": 0.20, "profit": 0.25},
}


# --- Volume discount curves ---
# Key = quantity multiplier (e.g., 2 = 2x base qty), value = discount range

VOLUME_DISCOUNT_CURVES: dict[float, dict[str, float]] = {
    1.0: {"min": 0.0, "max": 0.0},       # base quantity — no discount
    2.0: {"min": 10.0, "max": 15.0},      # 2x base → 10-15% off
    3.0: {"min": 13.0, "max": 18.0},      # 3x base → 13-18% off
    5.0: {"min": 20.0, "max": 25.0},      # 5x base → 20-25% off
    10.0: {"min": 25.0, "max": 32.0},     # 10x base → 25-32% off
    25.0: {"min": 30.0, "max": 38.0},     # 25x base → 30-38% off
    50.0: {"min": 35.0, "max": 42.0},     # 50x base → 35-42% off
}


# --- Import duty rates by HS code category ---
# Approximate US import duty rates for common product categories

DUTY_RATES_BY_HS_CATEGORY: dict[str, float] = {
    "electronics": 0.00,          # Most consumer electronics duty-free
    "electronics_accessories": 0.035,
    "apparel_cotton": 0.12,       # Cotton apparel ~12%
    "apparel_synthetic": 0.16,    # Synthetic apparel ~16%
    "apparel_leather": 0.08,
    "footwear": 0.10,             # Varies 6-48% but typical ~10%
    "home_textiles": 0.08,
    "kitchenware_metal": 0.035,
    "kitchenware_plastic": 0.05,
    "furniture_wood": 0.00,       # Most wood furniture duty-free
    "furniture_metal": 0.00,
    "toys": 0.00,                 # Most toys duty-free
    "jewelry_costume": 0.035,
    "jewelry_precious": 0.065,
    "beauty_cosmetics": 0.00,     # Most cosmetics duty-free
    "sporting_goods": 0.045,
    "pet_products": 0.025,
    "food_supplement": 0.06,
    "general_goods": 0.05,        # Default estimate
}


# --- Shipping cost per kg by method (USD) ---

SHIPPING_COST_PER_KG: dict[str, float] = {
    "sea_standard": 1.50,         # Standard sea freight, 30-45 days
    "sea_express": 2.80,          # Express sea freight, 18-25 days
    "air_economy": 6.00,          # Air cargo economy, 7-12 days
    "air_express": 12.00,         # Air express (DHL/FedEx), 3-5 days
    "rail_europe": 3.50,          # China-Europe rail, 18-22 days
    "epacket": 4.50,              # ePacket small parcels, 10-20 days
    "truck_domestic": 0.30,       # US domestic truck per kg
}

# Minimum shipping charges by method
SHIPPING_MINIMUMS: dict[str, float] = {
    "sea_standard": 300.0,
    "sea_express": 500.0,
    "air_economy": 50.0,
    "air_express": 25.0,
    "rail_europe": 400.0,
    "epacket": 3.0,
    "truck_domestic": 15.0,
}


# --- Insurance rates (fraction of declared value) ---

INSURANCE_RATES: dict[str, float] = {
    "basic": 0.008,               # Basic marine cargo insurance (0.8%)
    "standard": 0.015,            # Standard all-risk (1.5%)
    "comprehensive": 0.025,       # Comprehensive with war/strikes (2.5%)
    "high_value": 0.035,          # High-value goods — jewelry, electronics (3.5%)
    "fragile": 0.040,             # Fragile goods — ceramics, glass (4.0%)
}


# --- Common negotiation benchmarks ---

TYPICAL_MARGIN_TARGETS: dict[str, float] = {
    "private_label": 0.60,        # 60% margin target for private label
    "wholesale_resale": 0.40,     # 40% for wholesale resale
    "dropship": 0.25,             # 25% for dropship (lower control)
    "commodity": 0.20,            # 20% for commodity/generic products
    "luxury": 0.70,               # 70% for luxury/premium positioning
}
