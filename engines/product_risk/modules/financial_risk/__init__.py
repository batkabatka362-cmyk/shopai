"""Financial Risk Module — assesses capital exposure, cash flow, and ROI risks.

Evaluates capital at risk, cash flow timing, margin erosion, currency
exposure, refund/chargeback risk, and scaling capital requirements.
"""

from .code import assess_financial_risk
from .logic import (
    calculate_max_loss,
    assess_cash_flow_risk,
    recommend_capital_allocation,
)
from .rules import validate_financial_constraints, FINANCIAL_RULES
from .data import (
    CAPITAL_LOSS_PROBABILITIES,
    CASH_FLOW_BENCHMARKS,
    MARGIN_EROSION_RATES,
    CHARGEBACK_BENCHMARKS,
)
from .knowledge import FINANCIAL_KNOWLEDGE, get_financial_insight

__all__ = [
    "assess_financial_risk",
    "calculate_max_loss",
    "assess_cash_flow_risk",
    "recommend_capital_allocation",
    "validate_financial_constraints",
    "FINANCIAL_RULES",
    "CAPITAL_LOSS_PROBABILITIES",
    "CASH_FLOW_BENCHMARKS",
    "MARGIN_EROSION_RATES",
    "CHARGEBACK_BENCHMARKS",
    "FINANCIAL_KNOWLEDGE",
    "get_financial_insight",
]
