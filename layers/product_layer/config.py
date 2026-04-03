"""Product Layer — configuration."""

PRODUCT_LAYER_CONFIG = {
    "engines": [
        "product_selection",
        "product_filter",
        "product_scoring",
        "product_validation",
        "product_ranking",
        "product_risk",
        "product_lifecycle",
        "catalog",
    ],
    "required_engines": [
        "product_selection",
        "product_filter",
        "product_scoring",
        "product_validation",
        "product_ranking",
        "catalog",
    ],
    "optional_engines": [
        "product_risk",
        "product_lifecycle",
    ],
    "parallel_groups": [
        ["product_risk", "product_lifecycle"],
    ],
}
