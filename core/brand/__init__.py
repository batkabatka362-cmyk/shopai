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

__all__ = [
    "BrandCheck",
    "BrandGuard",
    "BrandIssue",
    "BrandRules",
]
