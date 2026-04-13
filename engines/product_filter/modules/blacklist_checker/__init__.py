"""
blacklist_checker — Check products against compliance blacklists.

Screens products for restricted categories, banned substances,
trademark violations, and platform-specific policy issues.
Returns pass/fail with severity levels: blocked, restricted, caution.
"""

from .code import check_blacklist
from .logic import (
    assess_risk_level,
    suggest_alternatives,
    check_platform_compliance,
)
from .rules import (
    BLOCKED_CATEGORIES,
    RESTRICTED_KEYWORDS,
    PLATFORM_RESTRICTIONS,
    get_rules_for_platform,
)
from .data import (
    RESTRICTED_CATEGORIES,
    BANNED_SUBSTANCES,
    TRADEMARK_TERMS,
    COUNTRY_RESTRICTIONS,
    get_substances_for_category,
)
from .knowledge import (
    COMPLIANCE_KNOWLEDGE,
    diagnose_violation,
    get_common_mistakes,
)

__all__ = [
    "check_blacklist",
    "assess_risk_level",
    "suggest_alternatives",
    "check_platform_compliance",
    "BLOCKED_CATEGORIES",
    "RESTRICTED_KEYWORDS",
    "PLATFORM_RESTRICTIONS",
    "get_rules_for_platform",
    "RESTRICTED_CATEGORIES",
    "BANNED_SUBSTANCES",
    "TRADEMARK_TERMS",
    "COUNTRY_RESTRICTIONS",
    "get_substances_for_category",
    "COMPLIANCE_KNOWLEDGE",
    "diagnose_violation",
    "get_common_mistakes",
]
