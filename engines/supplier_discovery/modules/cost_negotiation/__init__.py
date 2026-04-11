"""
Cost Negotiation Module
Helps negotiate better prices and terms with suppliers by analyzing
cost structures, estimating volume discounts, and recommending
negotiation strategies.
"""

from .code import plan_negotiation
from .logic import (
    decide_negotiation_strategy,
    calculate_volume_discount,
    evaluate_payment_terms,
    calculate_total_landed_cost,
)
from .rules import (
    MAX_UPFRONT_DEPOSIT_PCT,
    REQUIRE_SAMPLE_BEFORE_ORDER,
    REQUIRE_INSPECTION_BEFORE_BALANCE,
    REQUIRE_PAYMENT_PROTECTION,
    validate_deposit_amount,
    validate_payment_terms,
    validate_order_safeguards,
)
from .data import (
    COST_BREAKDOWNS_BY_TYPE,
    VOLUME_DISCOUNT_CURVES,
    DUTY_RATES_BY_HS_CATEGORY,
    SHIPPING_COST_PER_KG,
    INSURANCE_RATES,
)
from .knowledge import (
    get_negotiation_tactics,
    get_payment_term_strategies,
    get_walk_away_signals,
    get_seasonal_timing_advice,
    get_value_add_requests,
)

__all__ = [
    "plan_negotiation",
    "decide_negotiation_strategy",
    "calculate_volume_discount",
    "evaluate_payment_terms",
    "calculate_total_landed_cost",
    "validate_deposit_amount",
    "validate_payment_terms",
    "validate_order_safeguards",
    "MAX_UPFRONT_DEPOSIT_PCT",
    "REQUIRE_SAMPLE_BEFORE_ORDER",
    "REQUIRE_INSPECTION_BEFORE_BALANCE",
    "REQUIRE_PAYMENT_PROTECTION",
    "COST_BREAKDOWNS_BY_TYPE",
    "VOLUME_DISCOUNT_CURVES",
    "DUTY_RATES_BY_HS_CATEGORY",
    "SHIPPING_COST_PER_KG",
    "INSURANCE_RATES",
    "get_negotiation_tactics",
    "get_payment_term_strategies",
    "get_walk_away_signals",
    "get_seasonal_timing_advice",
    "get_value_add_requests",
]
