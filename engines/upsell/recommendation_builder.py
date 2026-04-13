"""Upsell Engine — recommendation builder.

Assembles final upsell recommendations by combining all prior analyses:
candidates, price gaps, value propositions, conversion estimates, and
timing recommendations into actionable output.

Model note: Uses Qwen for final messaging and placement decisions.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Placement mapping: timing -> recommended UI placement
# ---------------------------------------------------------------------------

_PLACEMENT_MAP: dict[str, str] = {
    "product_page": "inline_comparison_widget",
    "cart": "cart_sidebar_upgrade_card",
    "checkout": "checkout_banner_minimal",
    "post_purchase": "confirmation_page_featured",
    "email_followup": "email_hero_section",
}

# ---------------------------------------------------------------------------
# CTA templates by urgency
# ---------------------------------------------------------------------------

_CTA_TEMPLATES: dict[str, str] = {
    "high": "Upgrade Now",
    "medium": "See the Upgrade",
    "low": "Compare Options",
}

# ---------------------------------------------------------------------------
# Maximum recommendations to return
# ---------------------------------------------------------------------------

_MAX_RECOMMENDATIONS = 5


def build_recommendations(
    candidates: list[dict[str, Any]],
    price_gaps: list[dict[str, Any]],
    value_propositions: list[dict[str, Any]],
    conversion_estimates: list[dict[str, Any]],
    timing_recommendations: list[dict[str, Any]],
    current_price: float,
) -> dict[str, Any]:
    """Build final upsell recommendations.

    Combines all analyses into ranked, actionable recommendations
    sorted by expected revenue impact.

    Args:
        candidates: UpgradeCandidate list.
        price_gaps: PriceGapAnalysis list.
        value_propositions: ValueProposition list.
        conversion_estimates: ConversionEstimate list.
        timing_recommendations: TimingRecommendation list.
        current_price: Current product price.

    Returns:
        Structured dict with ranked UpsellRecommendation list.
    """
    try:
        # Index everything by product_id
        gap_map = _index_by_pid(price_gaps)
        prop_map = _index_by_pid(value_propositions)
        conv_map = _index_by_pid(conversion_estimates)
        timing_map = _index_by_pid(timing_recommendations)

        recommendations: list[dict[str, Any]] = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            product_id = str(candidate.get("product_id", ""))
            title = str(candidate.get("title", ""))

            gap = gap_map.get(product_id, {})
            prop = prop_map.get(product_id, {})
            conv = conv_map.get(product_id, {})
            timing = timing_map.get(product_id, {})

            rec = _build_single(
                product_id=product_id,
                title=title,
                candidate=candidate,
                gap=gap,
                prop=prop,
                conv=conv,
                timing=timing,
                current_price=current_price,
            )

            # Only include if expected revenue is positive
            if rec["expected_revenue"] > 0:
                recommendations.append(rec)

        # Sort by expected revenue descending
        recommendations.sort(key=lambda r: r["expected_revenue"], reverse=True)
        recommendations = recommendations[:_MAX_RECOMMENDATIONS]

        # Identify best upsell
        best_upsell = recommendations[0] if recommendations else None

        # Aggregate metrics
        total_expected_revenue = sum(r["expected_revenue"] for r in recommendations)
        confidences = [
            conv_map.get(r["product_id"], {}).get("confidence", 0.5)
            for r in recommendations
        ]
        avg_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        return {
            "status": "success",
            "upsells": recommendations,
            "best_upsell": best_upsell,
            "estimated_revenue_increase": round(total_expected_revenue, 2),
            "confidence": round(avg_confidence, 4),
            "count": len(recommendations),
        }
    except Exception as exc:
        return {
            "status": "error",
            "upsells": [],
            "best_upsell": None,
            "estimated_revenue_increase": 0.0,
            "confidence": 0.0,
            "error": f"Recommendation building failed: {exc}",
        }


def _build_single(
    product_id: str,
    title: str,
    candidate: dict[str, Any],
    gap: dict[str, Any],
    prop: dict[str, Any],
    conv: dict[str, Any],
    timing: dict[str, Any],
    current_price: float,
) -> dict[str, Any]:
    """Build a single recommendation."""

    price_increase = float(gap.get("absolute_difference", 0.0))
    if price_increase <= 0:
        price_increase = float(candidate.get("price", 0.0)) - current_price

    conversion_prob = float(conv.get("final_probability", 0.05))
    expected_revenue = round(price_increase * conversion_prob, 2)

    headline = str(prop.get("headline", f"Upgrade to {title}"))
    best_timing = str(timing.get("best_timing", "product_page"))
    urgency = str(timing.get("urgency_level", "medium"))
    placement = _PLACEMENT_MAP.get(best_timing, "inline_comparison_widget")

    # Build messaging
    per_day_framing = str(prop.get("per_day_framing", ""))
    social_proof = str(prop.get("social_proof", ""))
    cta = _CTA_TEMPLATES.get(urgency, "See the Upgrade")

    body_parts = []
    if per_day_framing:
        body_parts.append(per_day_framing)
    if social_proof:
        body_parts.append(social_proof)
    body = ". ".join(body_parts) if body_parts else f"Get more with {title}"

    messaging = {
        "headline": headline,
        "body": body,
        "cta": cta,
    }

    # Extra features for the model note
    extra_count = len(candidate.get("extra_features", []))
    relevance = float(candidate.get("relevance_score", 0.0))

    return {
        "product_id": product_id,
        "title": title,
        "price_increase": round(price_increase, 2),
        "value_proposition": headline,
        "conversion_probability": round(conversion_prob, 4),
        "expected_revenue": expected_revenue,
        "timing": best_timing,
        "messaging": messaging,
        "placement": placement,
        "model_note": (
            f"Qwen: recommendation built — "
            f"${price_increase:.2f} increase, "
            f"{conversion_prob:.1%} conversion, "
            f"${expected_revenue:.2f} expected revenue, "
            f"{extra_count} extra features, "
            f"relevance {relevance:.2f}, "
            f"show at {best_timing}"
        ),
    }


def _index_by_pid(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index a list of dicts by their product_id field."""
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict):
            pid = str(item.get("product_id", ""))
            if pid:
                result[pid] = item
    return result
