"""Pricing Layer — configuration."""

PRICING_LAYER_CONFIG = {
    "engines": [
        "pricing",
        "price_elasticity",
        "dynamic_pricing",
        "discount_strategy",
        "profitability_calculator",
        "profit_optimization",
        "payment_optimization",
    ],
    "required_engines": [
        "pricing",
        "profitability_calculator",
    ],
    "optional_engines": [
        "price_elasticity",
        "dynamic_pricing",
        "discount_strategy",
        "profit_optimization",
        "payment_optimization",
    ],
    "parallel_groups": [],
}
