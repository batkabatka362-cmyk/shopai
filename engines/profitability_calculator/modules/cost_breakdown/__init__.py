"""Cost Breakdown Module — calculates ALL costs of selling a product.

Goes beyond COGS to capture every cost that eats into margin: shipping,
packaging, payment processing, platform fees, advertising, returns,
warehousing, customs duties, and insurance.
"""

from .code import calculate_cost_breakdown
from .logic import (
    identify_cost_reduction_opportunities,
    compare_cost_structures,
    calculate_minimum_viable_price,
)
from .rules import validate_cost_constraints, COST_RULES
from .data import (
    PAYMENT_PROCESSING_RATES,
    SHIPPING_RATES_BY_WEIGHT,
    PACKAGING_COSTS,
    DUTY_RATES,
    SHOPIFY_PLAN_FEES,
    INSURANCE_RATES,
    WAREHOUSE_RATES,
)
from .knowledge import COST_KNOWLEDGE, get_cost_insight

__all__ = [
    "calculate_cost_breakdown",
    "identify_cost_reduction_opportunities",
    "compare_cost_structures",
    "calculate_minimum_viable_price",
    "validate_cost_constraints",
    "COST_RULES",
    "PAYMENT_PROCESSING_RATES",
    "SHIPPING_RATES_BY_WEIGHT",
    "PACKAGING_COSTS",
    "DUTY_RATES",
    "SHOPIFY_PLAN_FEES",
    "INSURANCE_RATES",
    "WAREHOUSE_RATES",
    "COST_KNOWLEDGE",
    "get_cost_insight",
]
