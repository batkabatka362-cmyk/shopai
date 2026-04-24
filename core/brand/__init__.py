"""Brand style-guide enforcement.

Public surface — one class + one dataclass:

    from core.brand import BrandGuard, BrandCheck

    guard = BrandGuard.from_metafields(metafields)
    check = guard.check_content(
        text="CRAZY DEAL — buy NOW!!!",
        surface="ad_copy",
    )
    if not check.passed:
        # Content failed brand rules; log + reject or escalate.
        for issue in check.issues:
            print(issue.code, issue.reason)
"""
from core.brand.brand_guard import (
    BrandCheck,
    BrandGuard,
    BrandIssue,
    BrandRules,
)
from core.brand.pre_ship import (
    BrandGateRejected,
    GateVerdict,
    brand_gate,
    reload_brand_rules,
)

__all__ = [
    "BrandCheck",
    "BrandGateRejected",
    "BrandGuard",
    "BrandIssue",
    "BrandRules",
    "GateVerdict",
    "brand_gate",
    "reload_brand_rules",
]
