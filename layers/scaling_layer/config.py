"""Scaling Layer — configuration.

Neither engine is strictly required — scaling analysis is
informational and should not block the cycle.
"""

SCALING_LAYER_CONFIG = {
    "engines": [
        "marketplace",
        "infinite_scaling",
    ],
    "required_engines": [],
    "optional_engines": [
        "marketplace",
        "infinite_scaling",
    ],
    "parallel_groups": [],
}
