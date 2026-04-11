"""Risk Disclosure Module — honestly discloses risks of the selection.

Lists all identified risks with severity, mitigation plans, and
worst-case scenarios. Prioritizes transparency over optimism.
"""

from .code import disclose_risks
from .logic import prioritize_risks, generate_mitigation_plan, calculate_worst_case
from .rules import RISK_DISCLOSURE_RULES, validate_risk_disclosure
from .data import RISK_TEMPLATES, MITIGATION_LIBRARY, WORST_CASE_FACTORS
from .knowledge import RISK_DISCLOSURE_KNOWLEDGE, get_risk_insight

__all__ = [
    "disclose_risks",
    "prioritize_risks",
    "generate_mitigation_plan",
    "calculate_worst_case",
    "RISK_DISCLOSURE_RULES",
    "validate_risk_disclosure",
    "RISK_TEMPLATES",
    "MITIGATION_LIBRARY",
    "WORST_CASE_FACTORS",
    "RISK_DISCLOSURE_KNOWLEDGE",
    "get_risk_insight",
]
