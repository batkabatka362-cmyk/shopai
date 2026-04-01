"""Blacklist decision logic — risk assessment, alternatives, platform compliance.

Functions that interpret raw blacklist check results and provide
actionable guidance: overall risk level, legal alternatives for
blocked products, and platform-specific compliance details.
"""
from __future__ import annotations

from typing import Any

from .rules import BLOCKED_CATEGORIES, RESTRICTED_CATEGORIES, PLATFORM_RESTRICTIONS


# Alternative product suggestions for commonly blocked items
_ALTERNATIVE_MAP = {
    "weapons": [
        "self-defense keychains (check local laws)",
        "personal safety alarms",
        "tactical flashlights",
        "pepper spray (where legal, age-restricted)",
    ],
    "drugs": [
        "herbal teas with wellness positioning",
        "aromatherapy diffusers and essential oils",
        "meditation and mindfulness accessories",
    ],
    "counterfeit": [
        "original designs inspired by trends (not specific brands)",
        "unbranded quality alternatives",
        "private label products with your own branding",
        "licensed merchandise (obtain official license)",
    ],
    "adult": [
        "lingerie and intimate apparel (mainstream platforms allow)",
        "bath and body products with sensual branding",
        "romance books and accessories",
    ],
    "tobacco": ["tobacco-free herbal alternatives", "novelty lighters and accessories"],
    "alcohol": ["non-alcoholic craft beverages", "cocktail accessories and barware"],
    "gambling": ["board games and party games", "game night accessories"],
    "supplements": ["whole food products (positioned as food)", "fitness accessories"],
    "cbd": ["non-CBD herbal topicals", "aromatherapy products for stress relief"],
    "endangered_species": ["sustainable faux alternatives", "recycled material accessories"],
    "explosives": ["party poppers and confetti launchers", "LED light-up novelties"],
}


def assess_risk_level(violations: list[dict[str, Any]]) -> dict[str, Any]:
    """Assess overall risk based on all detected violations.

    Args:
        violations: List of violation dicts with keys: category, severity, detail

    Returns:
        Overall risk assessment with recommendation.
    """
    if not violations:
        return {
            "risk_level": "clear",
            "score": 0,
            "can_proceed": True,
            "summary": "No violations detected. Product appears compliant.",
            "action": "Safe to list. Monitor for policy changes.",
        }

    severity_scores = {"blocked": 100, "restricted": 50, "caution": 20}
    max_severity = "caution"
    total_score = 0

    for v in violations:
        sev = v.get("severity", "caution")
        total_score += severity_scores.get(sev, 10)
        if severity_scores.get(sev, 0) > severity_scores.get(max_severity, 0):
            max_severity = sev

    counts = {
        "blocked": sum(1 for v in violations if v.get("severity") == "blocked"),
        "restricted": sum(1 for v in violations if v.get("severity") == "restricted"),
        "caution": sum(1 for v in violations if v.get("severity") == "caution"),
    }

    level_map = {
        "blocked": {
            "risk_level": "critical", "score": min(100, total_score),
            "can_proceed": False,
            "summary": f"BLOCKED: {counts['blocked']} critical violation(s). Cannot sell.",
            "action": "Do NOT list this product. Consider alternatives.",
        },
        "restricted": {
            "risk_level": "high", "score": min(80, total_score),
            "can_proceed": True,
            "summary": f"RESTRICTED: {counts['restricted']} restriction(s). Needs approval.",
            "action": "Obtain required licenses/approvals before listing.",
        },
        "caution": {
            "risk_level": "moderate", "score": min(40, total_score),
            "can_proceed": True,
            "summary": f"CAUTION: {counts['caution']} warning(s). Review flagged areas.",
            "action": "Proceed carefully. Address flagged concerns before scaling.",
        },
    }
    result = level_map[max_severity]
    result["violation_counts"] = counts
    return result


def suggest_alternatives(blocked_product: str) -> dict[str, Any]:
    """Suggest legal alternatives for a blocked or restricted product.

    Args:
        blocked_product: The product description or category that was blocked.

    Returns:
        Dict with alternatives and pivot strategy advice.
    """
    product_lower = blocked_product.lower()
    suggestions = []
    matched_category = None

    # Check blocked categories
    all_categories = {**BLOCKED_CATEGORIES, **RESTRICTED_CATEGORIES}
    for cat_key, cat_info in all_categories.items():
        keywords = cat_info.get("keywords", [])
        if any(kw in product_lower for kw in keywords) or cat_key in product_lower:
            matched_category = cat_key
            break

    if matched_category and matched_category in _ALTERNATIVE_MAP:
        suggestions = _ALTERNATIVE_MAP[matched_category]
    else:
        suggestions = [
            "Consider a different product category entirely",
            "Research trending products in unrestricted categories",
            "Focus on accessories or complementary products instead",
        ]

    return {
        "blocked_product": blocked_product,
        "matched_category": matched_category,
        "alternatives": suggestions,
        "pivot_strategy": (
            "Focus on the customer need, not the specific product. "
            "What problem does this product solve? Find a compliant "
            "product that addresses the same need."
        ),
    }


def check_platform_compliance(
    product: dict[str, Any],
    platform: str,
) -> dict[str, Any]:
    """Check product compliance for a specific platform.

    Args:
        product: Product dict with keys like name, category, description.
        platform: Target platform (shopify, amazon, facebook, google, tiktok).

    Returns:
        Platform-specific compliance result.
    """
    platform_key = platform.lower().strip()
    platform_rules = PLATFORM_RESTRICTIONS.get(platform_key)

    if not platform_rules:
        return {
            "platform": platform,
            "status": "unknown",
            "message": f"No specific rules found for platform '{platform}'",
            "recommendation": "Check the platform's policies manually",
        }

    product_name = (product.get("name", "") + " " + product.get("description", "")).lower()
    product_category = product.get("category", "").lower()
    issues = []

    # Check platform-specific blocked extras
    for blocked in platform_rules.get("blocked_extras", []):
        if blocked.lower() in product_name or blocked.lower() in product_category:
            issues.append({
                "type": "platform_blocked",
                "severity": "blocked",
                "detail": f"'{blocked}' is specifically blocked on {platform}",
            })

    # Check platform-specific restricted extras
    for restricted in platform_rules.get("restricted_extras", []):
        if restricted.lower() in product_name or restricted.lower() in product_category:
            issues.append({
                "type": "platform_restricted",
                "severity": "restricted",
                "detail": f"'{restricted}' requires approval on {platform}",
            })

    status = "pass"
    if any(i["severity"] == "blocked" for i in issues):
        status = "fail"
    elif issues:
        status = "conditional"

    return {
        "platform": platform,
        "status": status,
        "issues": issues,
        "issue_count": len(issues),
        "ad_policy_note": platform_rules.get("ad_policy", ""),
        "policy_url": platform_rules.get("policy_url", ""),
        "recommendation": (
            "Product is blocked on this platform" if status == "fail"
            else "Product needs approval — check platform docs" if status == "conditional"
            else "Product appears compliant for this platform"
        ),
    }
