"""Market Research Engine — verdict builder.

Build market entry/expansion verdict from all research data.
"""
from __future__ import annotations

import copy
from typing import Any


def build_verdict(
    **kwargs: Any,
) -> dict[str, Any]:
    """Build market entry verdict.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with verdict, market_size, gaps, trends.
    """
    try:
        size_data = kwargs.get("size_estimator_data", {})
        gap_data = kwargs.get("gap_analyzer_data", {})
        trend_data = kwargs.get("trend_synthesizer_data", {})

        tam = float(size_data.get("tam", 0))
        som = float(size_data.get("som", 0))
        gaps = gap_data.get("gaps", [])
        trends = trend_data.get("trends", [])

        # Build verdict
        score = 0.0
        reasons: list[str] = []

        # Market size factor
        if som > 100000:
            score += 0.3
            reasons.append(f"Large obtainable market (${som:,.0f})")
        elif som > 10000:
            score += 0.2
            reasons.append(f"Moderate obtainable market (${som:,.0f})")
        else:
            reasons.append(f"Small obtainable market (${som:,.0f})")

        # Gap factor
        if len(gaps) >= 3:
            score += 0.3
            reasons.append(f"{len(gaps)} market gaps identified")
        elif gaps:
            score += 0.15
            reasons.append(f"{len(gaps)} market gap(s) found")

        # Trend factor
        strong_trends = [t for t in trends if t.get("strength", 0) > 0.7 and t.get("direction") == "up"]
        if strong_trends:
            score += 0.3
            reasons.append(f"{len(strong_trends)} strong upward trends")
        elif trends:
            score += 0.1

        score = round(min(score, 1.0), 2)
        if score >= 0.7:
            recommendation = "strong_entry"
        elif score >= 0.4:
            recommendation = "cautious_entry"
        else:
            recommendation = "avoid"

        market_size = {"tam": tam, "sam": size_data.get("sam", 0), "som": som}

        return {
            "status": "success",
            "result": {
                "market_size": market_size,
                "gaps": gaps,
                "trends": trends,
                "verdict": {
                    "recommendation": recommendation,
                    "confidence": score,
                    "reasoning": "; ".join(reasons),
                },
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Verdict building failed: {exc}"}
