"""Main legal risk assessment engine.

Evaluates legal and regulatory risks across six dimensions and returns
a structured assessment with the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import (
    get_regulatory_requirements,
    get_compliance_cost,
    get_liability_tier,
    COMPLIANCE_COST_RANGES,
    COMMON_IP_PITFALLS,
    LIABILITY_INSURANCE_RATES,
    PLATFORM_POLICY_RESTRICTIONS,
)


def assess_legal_risk(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Assess legal and regulatory risks for a product.

    Args:
        input_payload: dict with keys:
            - product_name (str): name or title of the product (required)
            - category (str): product category (required)
            - selling_price (float): retail price in USD (default 30.0)
            - is_imported (bool): whether product is imported (default True)
            - target_platforms (list[str]): e.g. ["amazon", "shopify"]
            - monthly_revenue_estimate (float): projected monthly revenue
            - makes_health_claims (bool): whether product makes health/wellness claims
            - target_children (bool): whether marketed to children under 12

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        product_name = input_payload.get("product_name")
        category = input_payload.get("category")

        if not product_name or not category:
            return _error("product_name and category are required fields")

        selling_price = input_payload.get("selling_price", 30.0)
        is_imported = input_payload.get("is_imported", True)
        platforms = input_payload.get("target_platforms", ["amazon", "shopify"])
        monthly_revenue = input_payload.get("monthly_revenue_estimate", 5000.0)
        health_claims = input_payload.get("makes_health_claims", False)
        target_children = input_payload.get("target_children", False)

        # --- 1. Regulatory compliance score ---
        reqs = get_regulatory_requirements(category)
        if target_children and category not in ("children_products", "children_toys"):
            reqs = get_regulatory_requirements("children_products")

        reg_score = _score_regulatory(reqs, health_claims)

        # --- 2. IP infringement risk ---
        ip_score, ip_flags = _score_ip_risk(product_name, category)

        # --- 3. Product liability exposure ---
        liability_tier = get_liability_tier(category)
        liability_score = _score_liability(liability_tier, selling_price, target_children)

        # --- 4. Advertising claim risk ---
        ad_score = _score_ad_claims(category, health_claims)

        # --- 5. Import restriction risk ---
        import_score = _score_import_risk(category, is_imported)

        # --- 6. Platform policy violation risk ---
        platform_score, platform_issues = _score_platform_risk(category, platforms)

        # --- Aggregate ---
        dimensions = {
            "regulatory_compliance": reg_score,
            "ip_infringement": ip_score,
            "product_liability": liability_score,
            "advertising_claims": ad_score,
            "import_restrictions": import_score,
            "platform_policy": platform_score,
        }
        overall_score = round(sum(dimensions.values()) / len(dimensions), 1)
        risk_level = _classify_risk(overall_score)

        # --- Compliance cost estimate ---
        cost_estimate = _estimate_compliance_costs(reqs, category, target_children)

        # --- Legal requirements ---
        legal_reqs = reqs["requirements"] if reqs["mandatory"] else []
        timeline = reqs["timeline_months"]

        insurance = LIABILITY_INSURANCE_RATES.get(liability_tier, {})
        premium_range = insurance.get("annual_premium", (500, 2000))

        return {
            "status": "success",
            "data": {
                "overall_risk_score": overall_score,
                "risk_level": risk_level,
                "dimensions": dimensions,
                "legal_requirements": legal_reqs,
                "compliance_timeline_months": {"min": timeline[0], "max": timeline[1]},
                "estimated_compliance_cost": cost_estimate,
                "ip_flags": ip_flags,
                "platform_issues": platform_issues,
                "liability_insurance_annual": {"low": premium_range[0], "high": premium_range[1]},
                "recommendation": _build_recommendation(overall_score, dimensions),
            },
            "meta": {
                "product_name": product_name,
                "category": category,
                "platforms_checked": platforms,
                "regulatory_agencies": reqs.get("agencies", []),
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Legal risk assessment failed: {exc}")


def _score_regulatory(reqs: dict[str, Any], health_claims: bool) -> int:
    """Score regulatory compliance risk 0-100 (higher = more risk)."""
    base = 20
    if reqs["mandatory"]:
        base += len(reqs["requirements"]) * 12
    if health_claims:
        base += 20
    timeline_max = reqs["timeline_months"][1]
    if timeline_max >= 12:
        base += 15
    elif timeline_max >= 6:
        base += 10
    return min(base, 100)


def _score_ip_risk(product_name: str, category: str) -> tuple[int, list[str]]:
    """Score IP infringement risk and return specific flags."""
    score = 15
    flags = []
    for pitfall in COMMON_IP_PITFALLS:
        if pitfall["category"] == category or pitfall["category"] in category:
            freq_map = {"very_high": 30, "high": 20, "medium": 12, "low": 5}
            score += freq_map.get(pitfall["frequency"], 10)
            flags.append(f"{pitfall['risk']}: {pitfall['detail']}")
    name_lower = product_name.lower()
    brand_keywords = ["pro", "max", "ultra", "elite", "premium", "plus"]
    if any(kw in name_lower for kw in brand_keywords):
        score += 8
        flags.append("Product name uses common trademarked modifiers — check USPTO")
    return min(score, 100), flags


def _score_liability(tier: str, price: float, children: bool) -> int:
    """Score product liability exposure."""
    tier_scores = {"low_risk": 15, "medium_risk": 35, "high_risk": 60, "very_high_risk": 80}
    score = tier_scores.get(tier, 35)
    if children:
        score += 15
    if price > 100:
        score += 5
    return min(score, 100)


def _score_ad_claims(category: str, health_claims: bool) -> int:
    """Score advertising claim risk."""
    base = 10
    high_scrutiny = ["supplements", "cosmetics", "food", "medical_devices", "beauty"]
    if category in high_scrutiny:
        base += 25
    if health_claims:
        base += 35
    return min(base, 100)


def _score_import_risk(category: str, is_imported: bool) -> int:
    """Score import restriction risk."""
    if not is_imported:
        return 5
    base = 20
    restricted = {"food": 25, "supplements": 25, "cosmetics": 15, "electronics": 15, "children_products": 20}
    base += restricted.get(category, 5)
    return min(base, 100)


def _score_platform_risk(category: str, platforms: list[str]) -> tuple[int, list[str]]:
    """Score platform policy violation risk."""
    score = 5
    issues = []
    for platform in platforms:
        restrictions = PLATFORM_POLICY_RESTRICTIONS.get(platform, [])
        for r in restrictions:
            if r["category"] == category or r["category"] in category:
                score += 20
                issues.append(f"{platform}: {r['restriction']}")
    return min(score, 100), issues


def _estimate_compliance_costs(reqs: dict[str, Any], category: str, children: bool) -> dict[str, int]:
    """Estimate total compliance costs."""
    total_low, total_high = 0, 0
    category_cert_map = {
        "supplements": "fda_supplement", "cosmetics": "fda_cosmetic",
        "electronics": "fcc_certification", "food": "fda_food",
        "medical_devices": "fda_medical_device",
    }
    cert_key = category_cert_map.get(category)
    if cert_key and cert_key in COMPLIANCE_COST_RANGES:
        costs = COMPLIANCE_COST_RANGES[cert_key]
        total_low += costs["low"]
        total_high += costs["high"]
    if children or category in ("children_products", "children_toys"):
        cpsc = COMPLIANCE_COST_RANGES["cpsc_testing"]
        total_low += cpsc["low"]
        total_high += cpsc["high"]
    return {"low": total_low, "high": total_high}


def _classify_risk(score: float) -> str:
    """Classify overall risk level from score."""
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "moderate"
    return "low"


def _build_recommendation(score: float, dimensions: dict[str, int]) -> str:
    """Build a summary recommendation string."""
    if score >= 70:
        return "HIGH LEGAL RISK — consult an attorney before proceeding; unresolved issues may block sales"
    if score >= 50:
        worst = max(dimensions, key=dimensions.get)
        return f"Elevated legal risk — address {worst.replace('_', ' ')} before launch"
    if score >= 30:
        return "Moderate legal risk — budget for compliance costs and timeline in your launch plan"
    return "Low legal risk — standard compliance steps should suffice"


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
