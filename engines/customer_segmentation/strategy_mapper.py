"""Customer Segmentation Engine — strategy mapper.

Maps each customer segment to an actionable marketing strategy:
retention, reactivation, upsell, nurture, reward.

Model note: Would use LLaMA for generating tailored strategy
descriptions and tactic recommendations.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

_STRATEGY_MAP: dict[str, dict[str, Any]] = {
    "VIP Champions": {
        "strategy_type": "reward",
        "description": (
            "Reward and retain highest-value customers with exclusive perks, "
            "early access, and personalized experiences to maintain loyalty."
        ),
        "tactics": [
            "Exclusive early-access to new products",
            "Personalized thank-you communications",
            "VIP loyalty tier with enhanced rewards",
            "Dedicated account manager or concierge",
            "Surprise and delight gifting program",
        ],
        "priority": "critical",
        "expected_impact": "Protect top revenue — 1% churn reduction = significant revenue saved",
    },
    "Loyal High-Value": {
        "strategy_type": "retention",
        "description": (
            "Strengthen loyalty through consistent value delivery, "
            "cross-sell opportunities, and recognition programs."
        ),
        "tactics": [
            "Loyalty program tier upgrade incentives",
            "Personalized cross-sell recommendations",
            "Anniversary and milestone recognition",
            "Referral program with premium rewards",
            "Exclusive content and community access",
        ],
        "priority": "high",
        "expected_impact": "Increase retention rate by 10-15% and grow share of wallet",
    },
    "Rising Stars": {
        "strategy_type": "nurture",
        "description": (
            "Accelerate rising customers toward loyalty with onboarding, "
            "education, and graduated incentives."
        ),
        "tactics": [
            "Progressive onboarding email sequences",
            "Category discovery recommendations",
            "Second-purchase incentive offer",
            "Product education and use-case content",
            "Social proof and community integration",
        ],
        "priority": "high",
        "expected_impact": "Convert 20-30% to loyal tier within 90 days",
    },
    "Active Regulars": {
        "strategy_type": "upsell",
        "description": (
            "Increase average order value and purchase frequency through "
            "targeted upsell and cross-sell campaigns."
        ),
        "tactics": [
            "Bundle offers and volume discounts",
            "Complementary product recommendations",
            "Limited-time upgrade promotions",
            "Subscription or auto-replenish offers",
            "Seasonal and event-based campaigns",
        ],
        "priority": "medium",
        "expected_impact": "Lift AOV by 15-25% and increase order frequency",
    },
    "New Customers": {
        "strategy_type": "nurture",
        "description": (
            "Welcome and onboard new customers to build habit and "
            "drive second purchase within critical first-60-day window."
        ),
        "tactics": [
            "Welcome email series with brand story",
            "First-purchase follow-up and review request",
            "Second-purchase discount incentive",
            "Product usage tips and guides",
            "Easy return and support access messaging",
        ],
        "priority": "high",
        "expected_impact": "Increase second-purchase rate by 25-40%",
    },
    "Bargain Seekers": {
        "strategy_type": "upsell",
        "description": (
            "Convert price-sensitive shoppers through strategic promotions, "
            "value messaging, and cart recovery."
        ),
        "tactics": [
            "Flash sale and clearance notifications",
            "Price-drop alerts on browsed items",
            "Cart abandonment recovery with small incentive",
            "Value comparison and savings messaging",
            "Free shipping threshold optimization",
        ],
        "priority": "medium",
        "expected_impact": "Recover 10-20% of abandoned carts, improve conversion",
    },
    "At-Risk Valuable": {
        "strategy_type": "retention",
        "description": (
            "Urgently re-engage valuable customers showing disengagement "
            "signals before they churn permanently."
        ),
        "tactics": [
            "Personal win-back email from brand leader",
            "Exclusive comeback offer with deadline",
            "Survey to understand disengagement reasons",
            "Product updates and new arrivals showcase",
            "Loyalty points expiration reminder",
        ],
        "priority": "critical",
        "expected_impact": "Recover 15-25% of at-risk valuable customers",
    },
    "At-Risk Standard": {
        "strategy_type": "retention",
        "description": (
            "Re-engage customers drifting away with targeted "
            "reminders and incentives."
        ),
        "tactics": [
            "We-miss-you email campaign",
            "Personalized discount offer",
            "New product highlight email",
            "Social proof re-engagement",
            "Simplified re-purchase path",
        ],
        "priority": "medium",
        "expected_impact": "Recover 10-15% of drifting customers",
    },
    "Dormant Recoverable": {
        "strategy_type": "reactivation",
        "description": (
            "Attempt reactivation of dormant customers who had meaningful "
            "past value through aggressive win-back campaigns."
        ),
        "tactics": [
            "Deep discount reactivation offer",
            "Product category refresh showcase",
            "Account reactivation with bonus credits",
            "Multi-channel outreach (email + SMS + retargeting)",
            "Feedback request to understand departure",
        ],
        "priority": "medium",
        "expected_impact": "Reactivate 5-10% of dormant valuable customers",
    },
    "Dormant Low-Value": {
        "strategy_type": "reactivation",
        "description": (
            "Low-cost reactivation attempt for dormant low-value customers. "
            "Minimal investment given low expected return."
        ),
        "tactics": [
            "Automated reactivation email (low cost)",
            "General promotional campaign inclusion",
            "Social media retargeting at low bid",
        ],
        "priority": "low",
        "expected_impact": "Reactivate 2-5% at minimal cost",
    },
    "Churned": {
        "strategy_type": "reactivation",
        "description": (
            "Last-resort reactivation for churned customers. Low probability "
            "but some may return with the right trigger."
        ),
        "tactics": [
            "Final win-back offer with deep discount",
            "Brand reinvention announcement",
            "Annual holiday campaign inclusion",
            "Sunset email for list hygiene",
        ],
        "priority": "low",
        "expected_impact": "Recover 1-3% of churned customers",
    },
}

_DEFAULT_STRATEGY: dict[str, Any] = {
    "strategy_type": "nurture",
    "description": "General engagement strategy for uncategorized customers.",
    "tactics": [
        "Broad promotional campaigns",
        "Category-based recommendations",
        "Brand awareness content",
    ],
    "priority": "low",
    "expected_impact": "Baseline engagement maintenance",
}


def map_strategies(
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map marketing strategies to each segment.

    Mutates segment dicts in-place to add 'strategy' field, and
    returns detailed strategy objects.

    Args:
        segments: List of segment dicts from segment_builder.

    Returns:
        Structured dict with strategy details per segment.
    """
    try:
        if not segments:
            return {"status": "success", "strategies": [], "count": 0}

        segs = copy.deepcopy(segments)
        strategies: list[dict[str, Any]] = []

        for seg in segs:
            seg_name = seg.get("name", "")
            strategy_def = _STRATEGY_MAP.get(seg_name, _DEFAULT_STRATEGY)

            # Set the short strategy type on the segment itself
            seg["strategy"] = strategy_def["strategy_type"]

            strategies.append({
                "segment_name": seg_name,
                "strategy_type": strategy_def["strategy_type"],
                "description": strategy_def["description"],
                "tactics": strategy_def["tactics"],
                "priority": strategy_def["priority"],
                "expected_impact": strategy_def["expected_impact"],
                "model_note": "Would use LLaMA for personalized tactic generation",
            })

        return {
            "status": "success",
            "segments": segs,
            "strategies": strategies,
            "count": len(strategies),
        }
    except Exception as exc:
        return {
            "status": "error",
            "strategies": [],
            "count": 0,
            "error": f"Strategy mapping failed: {exc}",
        }
