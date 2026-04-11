"""Supplier Risk module — supply chain dependency, quality, and geopolitical assessment."""
from .code import assess_supplier_risk
from .logic import recommend_supplier_diversification, calculate_safety_stock_for_risk, build_contingency_plan
from .rules import evaluate_rules
from .data import (
    COUNTRY_RISK_SCORES,
    SUPPLIER_FAILURE_RATES,
    LEAD_TIME_VARIANCE,
    get_country_risk,
    get_lead_time_variance,
)
from .knowledge import get_supplier_risk_insights, get_heuristics
