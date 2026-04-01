"""Default cost rates and reference data for cost breakdown calculations.

All dollar amounts in USD. Rates current as of 2026 averages.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Payment processing fees by provider
# Each entry: {"percent": transaction %, "fixed": per-transaction flat fee}
# ---------------------------------------------------------------------------
PAYMENT_PROCESSING_RATES: dict[str, dict[str, float]] = {
    "shopify_payments": {"percent": 0.029, "fixed": 0.30},
    "stripe": {"percent": 0.029, "fixed": 0.30},
    "paypal": {"percent": 0.0349, "fixed": 0.49},
    "square": {"percent": 0.029, "fixed": 0.30},
    "klarna": {"percent": 0.039, "fixed": 0.30},
    "afterpay": {"percent": 0.06, "fixed": 0.30},
    "affirm": {"percent": 0.055, "fixed": 0.30},
    "apple_pay": {"percent": 0.029, "fixed": 0.30},  # same as Stripe
    "manual_card": {"percent": 0.035, "fixed": 0.30},  # non-integrated terminal
}

DEFAULT_PAYMENT_PROVIDER = "shopify_payments"

# ---------------------------------------------------------------------------
# Shipping rates by weight tier (domestic US, ground)
# weight_max_kg: max weight for this tier, rate: cost in USD
# ---------------------------------------------------------------------------
SHIPPING_RATES_BY_WEIGHT: list[dict[str, float]] = [
    {"weight_max_kg": 0.25, "rate": 3.50, "label": "letter"},
    {"weight_max_kg": 0.50, "rate": 4.80, "label": "small_packet"},
    {"weight_max_kg": 1.00, "rate": 6.50, "label": "light_parcel"},
    {"weight_max_kg": 2.00, "rate": 8.90, "label": "standard_parcel"},
    {"weight_max_kg": 3.00, "rate": 11.20, "label": "medium_parcel"},
    {"weight_max_kg": 5.00, "rate": 14.50, "label": "heavy_parcel"},
    {"weight_max_kg": 10.00, "rate": 19.80, "label": "large_parcel"},
    {"weight_max_kg": 20.00, "rate": 28.50, "label": "oversized"},
    {"weight_max_kg": 50.00, "rate": 45.00, "label": "freight_small"},
]

INTERNATIONAL_SHIPPING_MULTIPLIER = 2.5

# ---------------------------------------------------------------------------
# Packaging costs by product size category
# ---------------------------------------------------------------------------
PACKAGING_COSTS: dict[str, dict[str, float]] = {
    "tiny": {"material": 0.15, "labor": 0.10, "total": 0.25},       # jewelry, accessories
    "small": {"material": 0.35, "labor": 0.15, "total": 0.50},      # phone case, cosmetics
    "medium": {"material": 0.75, "labor": 0.25, "total": 1.00},     # shoes, small electronics
    "large": {"material": 1.50, "labor": 0.50, "total": 2.00},      # clothing box, appliances
    "oversized": {"material": 3.00, "labor": 1.00, "total": 4.00},  # furniture, large items
    "fragile": {"material": 2.00, "labor": 0.75, "total": 2.75},    # glassware, ceramics
    "premium": {"material": 2.50, "labor": 1.00, "total": 3.50},    # luxury unboxing experience
}

# Volume discount multipliers for packaging
PACKAGING_VOLUME_DISCOUNTS: list[dict] = [
    {"min_qty": 1, "multiplier": 1.0},
    {"min_qty": 100, "multiplier": 0.85},
    {"min_qty": 500, "multiplier": 0.70},
    {"min_qty": 1000, "multiplier": 0.50},
    {"min_qty": 5000, "multiplier": 0.38},
    {"min_qty": 10000, "multiplier": 0.30},
]

# ---------------------------------------------------------------------------
# Customs duty rates by product category (% of declared value)
# ---------------------------------------------------------------------------
DUTY_RATES: dict[str, float] = {
    "clothing": 0.12,
    "footwear": 0.15,
    "electronics": 0.035,
    "furniture": 0.08,
    "toys": 0.06,
    "cosmetics": 0.065,
    "food_supplements": 0.05,
    "jewelry": 0.065,
    "textiles": 0.10,
    "bags_luggage": 0.08,
    "sporting_goods": 0.04,
    "auto_parts": 0.025,
    "kitchenware": 0.035,
    "general": 0.05,
}

# De minimis threshold — shipments below this value are duty-free
DUTY_DE_MINIMIS_USD = 800.0

# ---------------------------------------------------------------------------
# Shopify plan fees (monthly)
# ---------------------------------------------------------------------------
SHOPIFY_PLAN_FEES: dict[str, dict[str, float]] = {
    "basic": {"monthly": 39.0, "transaction_fee_if_not_shopify_payments": 0.02},
    "shopify": {"monthly": 105.0, "transaction_fee_if_not_shopify_payments": 0.01},
    "advanced": {"monthly": 399.0, "transaction_fee_if_not_shopify_payments": 0.005},
    "plus": {"monthly": 2300.0, "transaction_fee_if_not_shopify_payments": 0.0015},
}

DEFAULT_SHOPIFY_PLAN = "basic"

# ---------------------------------------------------------------------------
# Insurance rates (% of declared value)
# ---------------------------------------------------------------------------
INSURANCE_RATES: dict[str, float] = {
    "domestic_standard": 0.015,       # 1.5% of value
    "domestic_high_value": 0.02,      # items > $500
    "international_standard": 0.03,
    "international_high_value": 0.04, # items > $500 shipped internationally
    "fragile": 0.05,                  # fragile items, any destination
}

HIGH_VALUE_THRESHOLD = 500.0

# ---------------------------------------------------------------------------
# Warehouse / fulfillment rates
# ---------------------------------------------------------------------------
WAREHOUSE_RATES: dict[str, float] = {
    "storage_per_cuft_month": 0.75,      # per cubic foot per month
    "pick_and_pack_base": 1.50,          # flat fee per order
    "pick_and_pack_per_item": 0.50,      # additional per item in order
    "receiving_per_unit": 0.25,          # inbound receiving
    "kitting_per_unit": 0.75,            # assembly / bundling
    "label_per_unit": 0.10,              # barcode labeling
    "returns_processing": 3.00,          # per returned unit
}

# Average inventory turnover used to calculate monthly storage allocation
DEFAULT_INVENTORY_TURNOVER_DAYS = 45


def get_shipping_rate(weight_kg: float, international: bool = False) -> float:
    """Look up shipping cost for a given weight."""
    for tier in SHIPPING_RATES_BY_WEIGHT:
        if weight_kg <= tier["weight_max_kg"]:
            rate = tier["rate"]
            return rate * INTERNATIONAL_SHIPPING_MULTIPLIER if international else rate
    # Exceeds all tiers — use last tier + $1/kg overage
    last = SHIPPING_RATES_BY_WEIGHT[-1]
    base = last["rate"]
    overage = (weight_kg - last["weight_max_kg"]) * 1.0
    total = base + overage
    return total * INTERNATIONAL_SHIPPING_MULTIPLIER if international else total


def get_packaging_cost(size: str, quantity: int = 1) -> float:
    """Return per-unit packaging cost after volume discounts."""
    base = PACKAGING_COSTS.get(size, PACKAGING_COSTS["medium"])["total"]
    multiplier = 1.0
    for tier in PACKAGING_VOLUME_DISCOUNTS:
        if quantity >= tier["min_qty"]:
            multiplier = tier["multiplier"]
    return round(base * multiplier, 2)


def get_duty_rate(category: str) -> float:
    """Return duty rate for a product category."""
    return DUTY_RATES.get(category, DUTY_RATES["general"])


def get_insurance_rate(
    value: float, international: bool = False, fragile: bool = False
) -> float:
    """Return insurance rate based on value, destination, and fragility."""
    if fragile:
        return INSURANCE_RATES["fragile"]
    high_value = value > HIGH_VALUE_THRESHOLD
    if international:
        return INSURANCE_RATES["international_high_value" if high_value else "international_standard"]
    return INSURANCE_RATES["domestic_high_value" if high_value else "domestic_standard"]
