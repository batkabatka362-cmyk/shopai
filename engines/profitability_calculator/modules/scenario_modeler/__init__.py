"""
Scenario Modeler Module
=======================
Runs "what if" scenarios to model different outcomes before committing
to a business decision. Generates pessimistic, expected, and optimistic
projections with risk-weighted expected values.

Core capabilities:
- Generate default 3-scenario analysis (pessimistic / expected / optimistic)
- Custom scenario modeling (price, volume, ad spend variations)
- Risk-adjusted return calculations
- Downside protection analysis
- Key driver identification
- Go/no-go recommendations based on scenario outcomes
"""

MODULE_NAME = "scenario_modeler"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = "What-if scenario modeling for business decisions"

SCENARIO_WEIGHTS = {
    "pessimistic": 0.25,
    "expected": 0.50,
    "optimistic": 0.25,
}

DEFAULT_SCENARIOS = ["pessimistic", "expected", "optimistic"]

SCENARIO_MULTIPLIERS = {
    "pessimistic": 0.50,
    "expected": 1.00,
    "optimistic": 1.50,
}

from .code import model_scenarios
from .logic import (
    compare_scenarios,
    calculate_risk_adjusted_return,
    identify_key_drivers,
    recommend_go_no_go,
)
from .rules import (
    validate_scenario_survivability,
    validate_expected_profitability,
    validate_risk_tolerance,
    run_all_validations,
)
from .data import (
    SCENARIO_DISTRIBUTIONS,
    VARIANCE_RANGES,
    CORRELATION_FACTORS,
    get_distribution_for_product_type,
    get_variance_range,
)
from .knowledge import (
    SCENARIO_PLANNING_PRINCIPLES,
    get_principle,
    get_all_principles,
    get_principles_for_context,
)

__all__ = [
    "model_scenarios",
    "compare_scenarios",
    "calculate_risk_adjusted_return",
    "identify_key_drivers",
    "recommend_go_no_go",
    "validate_scenario_survivability",
    "validate_expected_profitability",
    "validate_risk_tolerance",
    "run_all_validations",
    "SCENARIO_DISTRIBUTIONS",
    "VARIANCE_RANGES",
    "CORRELATION_FACTORS",
    "get_distribution_for_product_type",
    "get_variance_range",
    "SCENARIO_PLANNING_PRINCIPLES",
    "get_principle",
    "get_all_principles",
    "get_principles_for_context",
]
