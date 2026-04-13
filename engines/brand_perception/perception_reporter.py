"""Brand Perception Engine — perception reporter.

Reports perception trends, threats, and opportunities
based on sentiment, mentions, and reputation data.

All logic is deterministic. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def report_perception(
    tracking: dict[str, Any],
    sentiment: dict[str, Any],
    reputation: dict[str, Any],
) -> dict[str, Any]:
    """Generate perception report with trends, threats, and opportunities.

    Args:
        tracking: Mention tracking result dict.
        sentiment: Sentiment aggregation result dict.
        reputation: Reputation scoring result dict.

    Returns:
        Structured dict with perception report.
    """
    try:
        total_mentions = int(tracking.get("total_mentions", 0))
        by_source = tracking.get("by_source", {})
        positive_pct = float(sentiment.get("positive_pct", 0.0))
        negative_pct = float(sentiment.get("negative_pct", 0.0))
        neutral_pct = float(sentiment.get("neutral_pct", 0.0))
        reputation_score = int(reputation.get("reputation_score", 0))
        top_pos_themes = sentiment.get("top_positive_themes", [])
        top_neg_themes = sentiment.get("top_negative_themes", [])

        trends: list[str] = []
        threats: list[str] = []
        opportunities: list[str] = []

        # Trends based on sentiment distribution
        if positive_pct > 60:
            trends.append("Strong positive sentiment dominates brand perception")
        elif negative_pct > 40:
            trends.append("Negative sentiment is growing — requires attention")
        elif neutral_pct > 50:
            trends.append("Brand awareness is low — most mentions are neutral")

        if total_mentions > 50:
            trends.append("High mention volume indicates strong brand visibility")
        elif total_mentions < 10:
            trends.append("Low mention volume — brand may lack market presence")

        if len(by_source) >= 4:
            trends.append("Brand presence spans multiple channels — good reach")

        # Threats
        if negative_pct > 30:
            threats.append(
                f"Negative sentiment at {negative_pct}% — risk of reputation damage"
            )
        if top_neg_themes:
            threats.append(
                f"Key negative themes: {', '.join(top_neg_themes)} — address promptly"
            )
        if reputation_score < 40:
            threats.append("Reputation score below 40 — urgent brand health concern")
        if total_mentions > 0 and negative_pct > positive_pct:
            threats.append("Negative mentions outnumber positive — sentiment reversal needed")

        # Opportunities
        if positive_pct > 50 and top_pos_themes:
            opportunities.append(
                f"Leverage positive themes ({', '.join(top_pos_themes)}) in marketing"
            )
        if neutral_pct > 40:
            opportunities.append(
                "Large neutral audience — opportunity to convert to brand advocates"
            )
        if len(by_source) < 3:
            opportunities.append(
                "Expand presence to more channels for broader reach"
            )
        if reputation_score > 70:
            opportunities.append(
                "Strong reputation — consider ambassador/referral programs"
            )

        # Ensure at least one item in each
        if not trends:
            trends.append("Insufficient data for trend analysis")
        if not threats:
            threats.append("No significant threats detected")
        if not opportunities:
            opportunities.append("Gather more data to identify opportunities")

        return {
            "status": "success",
            "report": {
                "trends": trends,
                "threats": threats,
                "opportunities": opportunities,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "report": {},
            "error": f"Perception reporting failed: {exc}",
        }
