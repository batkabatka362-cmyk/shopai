"""Operations Layer — configuration."""

OPERATIONS_LAYER_CONFIG = {
    "engines": [
        "inventory",
        "stock_prediction",
        "supplier",
        "supplier_discovery",
        "shipping_optimization",
        "returns_management",
    ],
    "required_engines": [
        "inventory",
        "shipping_optimization",
    ],
    "optional_engines": [
        "stock_prediction",
        "supplier",
        "supplier_discovery",
        "returns_management",
    ],
    "parallel_groups": [
        ["stock_prediction", "supplier"],
    ],
}
