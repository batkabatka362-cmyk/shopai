"""Brand Positioning Engine — strategy advisor.

Advises positioning strategy adjustments based on market gaps,
differentiation scores, and competitive landscape.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def advise_strategy(
    position_map: dict[str, Any],
    gaps: list[dict[str, Any]],
    differentiation_scores: list[dict[str, Any]],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Generate strategy recommendations and competitive advantages.

    Args:
        position_map: Position map dict.
        gaps: Market gap dicts.
        differentiation_scores: Differentiation score dicts.
        brand: Brand info dict.

    Returns:
        Structured dict with strategy recommendations and competitive advantages.
    """
    try:
        brand_quadrant = str(position_map.get("brand_quadrant", ""))
        brand_name = str(brand.get("name", "Our Brand"))
        recommendations: list[dict[str, Any]] = []
        competitive_advantages: list[str] = []

        # Strategy based on current quadrant
        if "Premium" in brand_quadrant:
            recommendations.append({
                "recommendation": "Reinforce premium positioning through exclusivity and superior experience",
                "priority": "high",
                "rationale": f"{brand_name} occupies the premium quadrant — double down on quality signals",
            })
            competitive_advantages.append("Premium brand positioning commands higher margins")

        elif "Value" in brand_quadrant:
            recommendations.append({
                "recommendation": "Emphasize value proposition — high quality at accessible prices",
                "priority": "high",
                "rationale": f"{brand_name} has the strongest competitive position: quality at a fair price",
            })
            competitive_advantages.append("Best value proposition in the market")

        elif "Economy" in brand_quadrant:
            recommendations.append({
                "recommendation": "Consider quality improvements to move toward the Value quadrant",
                "priority": "high",
                "rationale": "The Economy quadrant is vulnerable to price wars — quality differentiation is safer",
            })

        elif "Overpriced" in brand_quadrant:
            recommendations.append({
                "recommendation": "Urgent: either improve quality or reduce pricing to exit the Overpriced quadrant",
                "priority": "critical",
                "rationale": "The Overpriced quadrant is unsustainable — customers will migrate to better options",
            })

        # Gap-based recommendations
        for gap in gaps[:2]:
            if gap.get("opportunity_score", 0) > 50 and "Overpriced" not in gap.get("quadrant", ""):
                recommendations.append({
                    "recommendation": f"Explore the {gap['quadrant']} segment — {gap.get('description', '')}",
                    "priority": "medium",
                    "rationale": f"Market gap with opportunity score of {gap.get('opportunity_score', 0)}",
                })

        # Differentiation-based recommendations
        low_diff = [d for d in differentiation_scores if d.get("differentiation_score", 0) < 30]
        high_diff = [d for d in differentiation_scores if d.get("differentiation_score", 0) > 60]

        if low_diff:
            names = ", ".join(d.get("competitor_name", "") for d in low_diff[:3])
            recommendations.append({
                "recommendation": f"Increase differentiation from close competitors: {names}",
                "priority": "high",
                "rationale": "Low differentiation means direct competition on price — find unique angles",
            })

        if high_diff:
            for d in high_diff[:2]:
                for adv in d.get("unique_advantages", []):
                    if adv not in competitive_advantages:
                        competitive_advantages.append(adv)

        # Always include brand values as advantages
        brand_values = brand.get("values", [])
        if brand_values:
            competitive_advantages.append(
                f"Clear brand values ({', '.join(brand_values[:3])}) drive customer loyalty"
            )

        # Ensure at least one recommendation
        if not recommendations:
            recommendations.append({
                "recommendation": "Maintain current positioning while monitoring competitor movements",
                "priority": "medium",
                "rationale": "Current position appears stable — focus on execution",
            })

        if not competitive_advantages:
            competitive_advantages.append("Established market presence")

        return {
            "status": "success",
            "strategy": {
                "recommendations": recommendations,
                "competitive_advantages": competitive_advantages,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "strategy": {},
            "error": f"Strategy advising failed: {exc}",
        }
