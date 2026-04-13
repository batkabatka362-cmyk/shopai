"""Financial Layer — configuration."""

FINANCIAL_LAYER_CONFIG = {
    "engines": [
        "financial",
        "kpi_tracking",
        "monetization",
        "profit_optimization",
        "payment_optimization",
    ],
    "required_engines": [
        "financial",
        "profit_optimization",
    ],
    "optional_engines": [
        "kpi_tracking",
        "monetization",
        "payment_optimization",
    ],
    "parallel_groups": [
        ["kpi_tracking", "monetization"],
    ],
}
