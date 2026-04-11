"""
legal_checker — Check products for legal/regulatory compliance.

Evaluates products against FDA, CPSC, FCC, CPSIA, labeling, and
import restriction rules.  Returns per-product compliance status
(compliant / needs_certification / non_compliant) with estimated
certification cost and timeline.
"""

from .code import check_legal_compliance
from .logic import (
    assess_compliance_cost,
    recommend_compliance_path,
    estimate_certification_timeline,
)
from .rules import (
    REGULATORY_REQUIREMENTS,
    CERTIFICATION_REQUIREMENTS,
    LABELING_RULES,
    get_rules_for_category,
)
from .data import (
    AGENCY_CONTACTS,
    CERTIFICATION_COSTS,
    PROCESSING_TIMES,
    REQUIRED_DOCUMENTS,
    get_documents_for_category,
)
from .knowledge import (
    COMPLIANCE_HEURISTICS,
    diagnose_compliance_issues,
    get_compliance_tips,
)

__all__ = [
    "check_legal_compliance",
    "assess_compliance_cost",
    "recommend_compliance_path",
    "estimate_certification_timeline",
    "REGULATORY_REQUIREMENTS",
    "CERTIFICATION_REQUIREMENTS",
    "LABELING_RULES",
    "get_rules_for_category",
    "AGENCY_CONTACTS",
    "CERTIFICATION_COSTS",
    "PROCESSING_TIMES",
    "REQUIRED_DOCUMENTS",
    "get_documents_for_category",
    "COMPLIANCE_HEURISTICS",
    "diagnose_compliance_issues",
    "get_compliance_tips",
]
