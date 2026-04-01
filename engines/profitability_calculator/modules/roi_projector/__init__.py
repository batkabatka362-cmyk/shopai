"""ROI Projector Module — projects return on investment over time.

Generates 30/60/90/180/365-day ROI projections with conservative, expected,
and optimistic scenarios. Includes cumulative ROI curves, cash flow analysis,
annualized ROI, and opportunity cost comparison.
"""

from .code import project_roi
from .logic import (
    compare_product_roi,
    assess_investment_worthiness,
    calculate_opportunity_cost,
)
from .rules import evaluate_roi_rules, ROI_RULES
from .data import (
    GROWTH_CURVE_BENCHMARKS,
    MONTHLY_SEASONALITY,
    AD_SPEND_RAMP_BY_MONTH,
)
from .knowledge import ROI_KNOWLEDGE, get_roi_insight

__all__ = [
    "project_roi",
    "compare_product_roi",
    "assess_investment_worthiness",
    "calculate_opportunity_cost",
    "evaluate_roi_rules",
    "ROI_RULES",
    "GROWTH_CURVE_BENCHMARKS",
    "MONTHLY_SEASONALITY",
    "AD_SPEND_RAMP_BY_MONTH",
    "ROI_KNOWLEDGE",
    "get_roi_insight",
]
