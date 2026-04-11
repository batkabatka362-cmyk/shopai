"""Execution Layer — configuration.

execution_intelligence and time_intelligence are core.
autonomous_* engines are operational — optional if data insufficient.
"""

EXECUTION_LAYER_CONFIG = {
    "engines": [
        "execution_intelligence",
        "time_intelligence",
        "autonomous_decision",
        "autonomous_control",
        "autonomous_execution",
    ],
    "required_engines": [
        "execution_intelligence",
        "time_intelligence",
    ],
    "optional_engines": [
        "autonomous_decision",
        "autonomous_control",
        "autonomous_execution",
    ],
    "parallel_groups": [],
}
