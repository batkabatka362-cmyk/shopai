"""LegalCompliance — orchestrates product, advertising, and privacy compliance checks.

Flow file only — calls sub-modules, contains no logic.
"""
from __future__ import annotations

from typing import Any

from .product_compliance import check_product
from .advertising_rules import check_advertising
from .privacy_compliance import check_privacy

__all__ = [
    "LegalCompliance",
    "check_product",
    "check_advertising",
    "check_privacy",
]


class LegalCompliance:
    """Real-time compliance checking — flow orchestrator."""

    def full_audit(
        self,
        products: list[dict[str, Any]] | None = None,
        ad_content: list[str] | None = None,
        collects_data: bool = True,
        sells_to_children: bool = False,
        sells_to_eu: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"violations": [], "warnings": [], "compliant_areas": []}

        if products:
            product_results = [check_product(p) for p in products]
            violations = [r for r in product_results if not r["compliant"]]
            result["product_compliance"] = {
                "total_checked": len(product_results),
                "compliant": len(product_results) - len(violations),
                "non_compliant": len(violations),
                "details": product_results,
            }
            for v in violations:
                result["violations"].extend(v.get("violations", []))

        if ad_content:
            ad_results = [check_advertising(ad) for ad in ad_content]
            ad_violations = [r for r in ad_results if not r["compliant"]]
            result["advertising_compliance"] = {
                "total_checked": len(ad_results),
                "compliant": len(ad_results) - len(ad_violations),
                "non_compliant": len(ad_violations),
                "details": ad_results,
            }
            for v in ad_violations:
                result["violations"].extend(v.get("violations", []))

        if collects_data:
            privacy = check_privacy(sells_to_eu=sells_to_eu, sells_to_children=sells_to_children)
            result["privacy_compliance"] = privacy
            result["warnings"].extend(privacy.get("requirements", []))

        result["overall_compliant"] = len(result["violations"]) == 0
        result["violation_count"] = len(result["violations"])
        result["warning_count"] = len(result["warnings"])
        result["risk_level"] = (
            "critical" if len(result["violations"]) > 3
            else "high" if len(result["violations"]) > 0
            else "medium" if len(result["warnings"]) > 3
            else "low"
        )

        return result
