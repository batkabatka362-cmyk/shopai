"""
Differentiation Module
======================
Identifies how to differentiate from competitors by analyzing gaps in
product features, service, brand, content, and price. Scores opportunities
by impact, cost, and time to implement, then suggests defensible strategies.
"""

from .code import find_differentiation
from .logic import (
    rank_differentiation_strategies,
    estimate_differentiation_cost,
    assess_sustainability,
)
from .rules import (
    RULES,
    evaluate_rules,
    DEFENSIBILITY_MINIMUM_MONTHS,
    CUSTOMER_VALUE_THRESHOLD,
)
from .data import (
    STRATEGY_TEMPLATES,
    IMPLEMENTATION_COST_RANGES,
    TIME_TO_IMPLEMENT_ESTIMATES,
    SUSTAINABILITY_RATINGS,
    get_strategy_template,
    get_cost_range,
)
from .knowledge import (
    DIFFERENTIATION_INSIGHTS,
    DIFFERENTIATION_PLAYBOOKS,
    get_insight,
    get_playbook,
)

__all__ = [
    "find_differentiation",
    "rank_differentiation_strategies",
    "estimate_differentiation_cost",
    "assess_sustainability",
    "RULES",
    "evaluate_rules",
    "DEFENSIBILITY_MINIMUM_MONTHS",
    "CUSTOMER_VALUE_THRESHOLD",
    "STRATEGY_TEMPLATES",
    "IMPLEMENTATION_COST_RANGES",
    "TIME_TO_IMPLEMENT_ESTIMATES",
    "SUSTAINABILITY_RATINGS",
    "get_strategy_template",
    "get_cost_range",
    "DIFFERENTIATION_INSIGHTS",
    "DIFFERENTIATION_PLAYBOOKS",
    "get_insight",
    "get_playbook",
]

MODULE_NAME = "differentiation"
MODULE_VERSION = "1.0.0"
MODULE_DESCRIPTION = (
    "Identifies differentiation opportunities by analyzing competitor gaps "
    "in features, service, brand, content, and price. Recommends defensible "
    "strategies scored by impact, cost, and sustainability."
)

REQUIRED_INPUT_FIELDS = [
    "product_category",
    "competitors",
    "our_product",
]

OPTIONAL_INPUT_FIELDS = [
    "budget",
    "timeline_months",
    "brand_assets",
    "current_usps",
]

OUTPUT_FIELDS = [
    "gaps",
    "opportunities",
    "recommended_strategies",
    "usps",
    "overall_differentiation_score",
]
