"""Review Management Engine — improvement suggester.

Suggests product and service improvements based on review insights,
prioritized by frequency and estimated impact.

Suggestions are rule-driven, mapping complaint/expectation categories
to concrete improvement actions. No faking, no random numbers.

Model note: Uses Qwen for structured suggestion generation and prioritization.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Improvement mapping: insight description patterns → suggestions
# ---------------------------------------------------------------------------

_IMPROVEMENT_RULES: list[dict[str, Any]] = [
    {
        "match_keywords": ["poor quality", "cheap", "flimsy", "defective", "broke"],
        "area": "Product Quality",
        "suggestion": (
            "Upgrade materials and reinforce construction at critical stress points. "
            "Implement stricter quality control checks before shipping."
        ),
        "base_impact": 0.85,
    },
    {
        "match_keywords": ["sizing", "too big", "too small", "runs large", "runs small"],
        "area": "Sizing & Fit",
        "suggestion": (
            "Provide detailed sizing charts with body measurements. "
            "Consider adding a fit-finder tool and include fit notes from verified buyers."
        ),
        "base_impact": 0.70,
    },
    {
        "match_keywords": ["slow shipping", "delayed", "late", "took forever"],
        "area": "Shipping & Fulfillment",
        "suggestion": (
            "Evaluate fulfillment partners and consider regional warehousing. "
            "Set more accurate delivery estimates and proactively notify customers of delays."
        ),
        "base_impact": 0.65,
    },
    {
        "match_keywords": ["overpriced", "expensive", "rip-off", "not worth", "waste of money"],
        "area": "Pricing & Value Perception",
        "suggestion": (
            "Review pricing relative to competitor offerings. Consider bundling, "
            "loyalty discounts, or enhancing perceived value through improved packaging "
            "and product descriptions."
        ),
        "base_impact": 0.60,
    },
    {
        "match_keywords": ["uncomfortable", "scratchy", "rough", "heavy", "painful"],
        "area": "Comfort & Ergonomics",
        "suggestion": (
            "Conduct user comfort testing and switch to softer or more ergonomic "
            "materials. Gather specific feedback on discomfort areas."
        ),
        "base_impact": 0.70,
    },
    {
        "match_keywords": ["misleading", "not as described", "different from", "false", "scam"],
        "area": "Product Listing Accuracy",
        "suggestion": (
            "Audit all product listings for accuracy. Use real product photos, "
            "update descriptions to match actual specifications, and add disclaimer "
            "notes where necessary."
        ),
        "base_impact": 0.80,
    },
    {
        "match_keywords": ["rude", "unhelpful", "no response", "ignored", "terrible service"],
        "area": "Customer Support",
        "suggestion": (
            "Invest in customer service training focused on empathy and resolution speed. "
            "Implement SLA tracking and escalation procedures for unresolved issues."
        ),
        "base_impact": 0.75,
    },
    {
        "match_keywords": ["damaged", "scratched", "dented", "stained", "dirty"],
        "area": "Packaging & Transit Protection",
        "suggestion": (
            "Upgrade packaging materials and add protective inserts. "
            "Work with carriers to reduce handling damage and consider insurance "
            "for high-value items."
        ),
        "base_impact": 0.65,
    },
    {
        "match_keywords": ["missing", "wish it had", "would be nice", "should have"],
        "area": "Feature Gaps",
        "suggestion": (
            "Compile a feature request list from customer feedback. Prioritize "
            "additions that appear most frequently and align with the product roadmap."
        ),
        "base_impact": 0.55,
    },
    {
        "match_keywords": ["expected", "thought it would", "should be", "hoped"],
        "area": "Expectation Management",
        "suggestion": (
            "Improve pre-purchase communication: add FAQ sections, comparison tables, "
            "and clearer specification details. Highlight limitations alongside strengths."
        ),
        "base_impact": 0.50,
    },
]


def suggest_improvements(
    insights: list[dict[str, Any]],
    summary: dict[str, Any],
    sentiment: dict[str, Any],
) -> dict[str, Any]:
    """Suggest improvements based on extracted insights.

    Args:
        insights: List of InsightItem dicts from insight_extractor.
        summary: Aggregated review summary.
        sentiment: Aggregate sentiment data.

    Returns:
        Structured dict with list of ImprovementItem data.
    """
    try:
        insight_items = copy.deepcopy(insights)

        if not insight_items:
            return {
                "status": "success",
                "improvements": [],
            }

        total_reviews = int(summary.get("total_reviews", 1)) or 1
        negative_pct = float(sentiment.get("negative_pct", 0.0))

        suggestions: list[dict[str, Any]] = []
        seen_areas: set[str] = set()

        # Match insights to improvement rules
        for insight in insight_items:
            # Only generate improvements for complaints and unmet expectations
            category = insight.get("category", "")
            if category not in ("complaint", "expectation"):
                continue

            description_lower = insight.get("description", "").lower()
            frequency = int(insight.get("frequency", 0))

            for rule in _IMPROVEMENT_RULES:
                if rule["area"] in seen_areas:
                    continue

                if _matches_rule(description_lower, rule["match_keywords"]):
                    # Compute priority based on frequency and impact
                    freq_ratio = frequency / total_reviews
                    impact = rule["base_impact"] * (1 + freq_ratio)
                    impact = min(1.0, round(impact, 2))

                    priority = _classify_priority(impact, freq_ratio, negative_pct)

                    suggestions.append({
                        "area": rule["area"],
                        "suggestion": rule["suggestion"],
                        "priority": priority,
                        "estimated_impact": impact,
                        "source_insight": insight.get("description", ""),
                        "model_note": f"Qwen: priority={priority}, impact={impact}, freq_ratio={freq_ratio:.2f}",
                    })
                    seen_areas.add(rule["area"])
                    break

        # Sort by priority (high > medium > low) then by impact
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(
            key=lambda s: (priority_order.get(s["priority"], 3), -s["estimated_impact"]),
        )

        return {
            "status": "success",
            "improvements": suggestions,
        }
    except Exception as exc:
        return {
            "status": "error",
            "improvements": [],
            "error": f"Improvement suggestion failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _matches_rule(description: str, keywords: list[str]) -> bool:
    """Check if any rule keyword appears in the insight description."""
    for kw in keywords:
        if kw in description:
            return True
    return False


def _classify_priority(
    impact: float,
    freq_ratio: float,
    negative_pct: float,
) -> str:
    """Classify improvement priority based on impact, frequency, and negativity.

    High priority: high impact + frequent or high negativity overall.
    Medium priority: moderate impact or frequency.
    Low priority: low impact and low frequency.
    """
    if impact >= 0.75 and (freq_ratio >= 0.15 or negative_pct >= 30.0):
        return "high"
    elif impact >= 0.55 or freq_ratio >= 0.10:
        return "medium"
    return "low"
