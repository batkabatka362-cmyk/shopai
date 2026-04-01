"""
Competitor Finder — Business Logic
Landscape assessment, vulnerable competitor detection, market share estimation.
"""

from .data import (
    REVIEW_COUNT_THRESHOLDS,
    STORE_AGE_BENCHMARKS,
    MARKET_CONCENTRATION_BENCHMARKS,
)


def assess_competitive_landscape(competitors):
    """Determine whether the market is crowded, moderate, or open."""
    if not competitors:
        return {"assessment": "unknown", "reasoning": "No competitor data", "metrics": {}}

    total = len(competitors)
    direct_count = sum(1 for c in competitors if c.get("classification") == "direct")
    avg_strength = sum(c.get("strength_score", 0) for c in competitors) / total
    high_strength_count = sum(1 for c in competitors if c.get("strength_score", 0) > 0.6)
    avg_rating = sum(c.get("rating", 0) for c in competitors) / total

    thresholds = MARKET_CONCENTRATION_BENCHMARKS
    direct_ratio = direct_count / total if total > 0 else 0

    if direct_count >= thresholds["crowded_direct_min"] and avg_strength >= thresholds["crowded_avg_strength"]:
        assessment = "crowded"
        reasoning = (
            f"Found {direct_count} direct competitors with average strength "
            f"{avg_strength:.2f}. The market is saturated with strong players."
        )
    elif direct_count <= thresholds["open_direct_max"] and avg_strength < thresholds["open_avg_strength"]:
        assessment = "open"
        reasoning = (
            f"Only {direct_count} direct competitors with average strength "
            f"{avg_strength:.2f}. Significant opportunity exists."
        )
    else:
        assessment = "moderate"
        reasoning = (
            f"Found {direct_count} direct competitors with average strength "
            f"{avg_strength:.2f}. Market has room but faces competition."
        )

    return {
        "assessment": assessment,
        "reasoning": reasoning,
        "metrics": {
            "total_competitors": total,
            "direct_competitors": direct_count,
            "direct_ratio": round(direct_ratio, 3),
            "average_strength": round(avg_strength, 4),
            "high_strength_count": high_strength_count,
            "average_rating": round(avg_rating, 2),
        },
    }


def identify_vulnerable_competitors(competitors):
    """Find competitors showing weakness: low rating, stagnation, poor catalog."""
    vulnerable = []

    for comp in competitors:
        reasons = []
        rating = comp.get("rating", 0)
        review_count = comp.get("review_count", 0)
        store_age = comp.get("store_age_years", 0)
        product_count = comp.get("product_count", 0)
        strength = comp.get("strength_score", 0)

        if rating < 3.5 and rating > 0:
            reasons.append(f"Low rating ({rating}/5.0) indicates customer dissatisfaction")

        if store_age > STORE_AGE_BENCHMARKS["mature"] and review_count < REVIEW_COUNT_THRESHOLDS["low"]:
            reasons.append(
                f"Established store ({store_age}yr) with very few reviews "
                f"({review_count}) suggests stagnation"
            )

        if product_count <= 2 and strength < 0.3:
            reasons.append("Minimal product catalog with low overall strength")

        reviews_per_year = review_count / store_age if store_age > 0 else review_count
        if reviews_per_year < 10 and store_age >= 1:
            reasons.append(
                f"Very low review velocity ({reviews_per_year:.1f}/year) "
                f"indicates weak sales momentum"
            )

        if rating > 0 and rating < 4.0 and review_count > REVIEW_COUNT_THRESHOLDS["moderate"]:
            reasons.append(
                f"Moderate reviews ({review_count}) but below-average rating "
                f"({rating}) — customers are finding better options"
            )

        if reasons:
            vulnerable.append({
                "name": comp.get("name", "Unknown"),
                "strength_score": strength,
                "classification": comp.get("classification", "unknown"),
                "vulnerabilities": reasons,
                "vulnerability_count": len(reasons),
            })

    vulnerable.sort(key=lambda v: v["vulnerability_count"], reverse=True)
    return vulnerable


def estimate_market_share_distribution(competitors):
    """Estimate market share percentages based on estimated revenue."""
    total_revenue = sum(c.get("estimated_revenue", 0) for c in competitors)

    if total_revenue == 0:
        equal_share = round(100.0 / len(competitors), 2) if competitors else 0
        return {
            "distribution": [{"name": c.get("name", "Unknown"), "share_pct": equal_share} for c in competitors],
            "summary": {"method": "equal_distribution", "top3_combined_share": round(equal_share * min(3, len(competitors)), 2)},
        }

    distribution = sorted(
        [{"name": c.get("name", "Unknown"), "share_pct": round((c.get("estimated_revenue", 0) / total_revenue) * 100, 2),
          "estimated_revenue": c.get("estimated_revenue", 0), "classification": c.get("classification", "unknown")}
         for c in competitors],
        key=lambda d: d["share_pct"], reverse=True,
    )
    top3_share = sum(d["share_pct"] for d in distribution[:3])
    bottom_half_share = sum(d["share_pct"] for d in distribution[len(distribution) // 2:])

    return {
        "distribution": distribution,
        "summary": {
            "method": "revenue_based",
            "top3_combined_share": round(top3_share, 2),
            "bottom_half_combined_share": round(bottom_half_share, 2),
            "total_revenue_estimated": total_revenue,
            "leader_name": distribution[0]["name"] if distribution else None,
            "leader_share_pct": distribution[0]["share_pct"] if distribution else 0,
        },
    }
