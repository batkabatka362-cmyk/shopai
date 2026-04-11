"""
shipping_feasibility — Evaluate whether a product is feasible to ship profitably.

Analyses weight, dimensional weight, fragility, hazmat classification,
temperature sensitivity, size constraints, and international viability
to produce a feasible / marginal / infeasible verdict.
"""

from .code import check_shipping_feasibility
from .logic import (
    recommend_shipping_method,
    calculate_shipping_margin_impact,
    optimize_packaging,
)
from .rules import (
    MAX_SHIPPING_COST_PCT,
    MARGINAL_SHIPPING_COST_PCT,
    check_weight_limit,
    check_size_constraints,
    check_hazmat_restrictions,
    check_battery_rules,
    check_liquid_restrictions,
    check_fragile_requirements,
    compute_surcharges,
)
from .data import (
    CARRIER_LIMITS,
    DIM_WEIGHT_DIVISORS,
    COST_BY_WEIGHT_TIER,
    SURCHARGES,
    HAZMAT_CATEGORIES,
    INTERNATIONAL_RESTRICTIONS,
    get_shipping_cost_estimate,
    get_hazmat_info,
)
from .knowledge import (
    SHIPPING_HEURISTICS,
    get_heuristic_warnings,
    diagnose_shipping_result,
)

__all__ = [
    "check_shipping_feasibility",
    "recommend_shipping_method",
    "calculate_shipping_margin_impact",
    "optimize_packaging",
    "MAX_SHIPPING_COST_PCT",
    "MARGINAL_SHIPPING_COST_PCT",
    "check_weight_limit",
    "check_size_constraints",
    "check_hazmat_restrictions",
    "check_battery_rules",
    "check_liquid_restrictions",
    "check_fragile_requirements",
    "compute_surcharges",
    "CARRIER_LIMITS",
    "DIM_WEIGHT_DIVISORS",
    "COST_BY_WEIGHT_TIER",
    "SURCHARGES",
    "HAZMAT_CATEGORIES",
    "INTERNATIONAL_RESTRICTIONS",
    "get_shipping_cost_estimate",
    "get_hazmat_info",
    "SHIPPING_HEURISTICS",
    "get_heuristic_warnings",
    "diagnose_shipping_result",
]
