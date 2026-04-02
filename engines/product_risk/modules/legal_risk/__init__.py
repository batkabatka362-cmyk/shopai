"""Legal Risk Module — assesses legal and regulatory risks for products.

Evaluates regulatory compliance (FDA/CPSC/FCC), IP infringement risk,
product liability exposure, advertising claim risk, import restrictions,
and platform policy violations.
"""

from .code import assess_legal_risk
from .logic import (
    recommend_legal_path,
    estimate_liability_exposure,
    check_ip_risk,
)
from .rules import validate_legal_constraints, LEGAL_RULES
from .data import (
    REGULATORY_REQUIREMENTS,
    COMPLIANCE_COST_RANGES,
    COMMON_IP_PITFALLS,
    LIABILITY_INSURANCE_RATES,
    PLATFORM_POLICY_RESTRICTIONS,
)
from .knowledge import LEGAL_KNOWLEDGE, get_legal_insight

__all__ = [
    "assess_legal_risk",
    "recommend_legal_path",
    "estimate_liability_exposure",
    "check_ip_risk",
    "validate_legal_constraints",
    "LEGAL_RULES",
    "REGULATORY_REQUIREMENTS",
    "COMPLIANCE_COST_RANGES",
    "COMMON_IP_PITFALLS",
    "LIABILITY_INSURANCE_RATES",
    "PLATFORM_POLICY_RESTRICTIONS",
    "LEGAL_KNOWLEDGE",
    "get_legal_insight",
]
