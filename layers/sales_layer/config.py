"""Sales Layer — configuration."""

SALES_LAYER_CONFIG = {
    "engines": [
        "cart_recovery",
        "search_optimization",
        "cross_sell",
        "upsell",
        "bundle",
        "conversion_tracking",
    ],
    "required_engines": [
        "cart_recovery",
        "search_optimization",
        "conversion_tracking",
    ],
    "optional_engines": [
        "cross_sell",
        "upsell",
        "bundle",
    ],
    "parallel_groups": [
        ["cart_recovery", "search_optimization"],
        ["cross_sell", "upsell", "bundle"],
    ],
}
