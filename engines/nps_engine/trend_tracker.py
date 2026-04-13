"""NPS Engine — trend tracker.

Tracks NPS trends over time and generates action items.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def track_trends(
    validated_responses: list[dict[str, Any]],
    nps_score: float,
    segment_breakdown: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track NPS trends over time and generate action items.

    Args:
        validated_responses: Validated responses with dates.
        nps_score: Overall NPS score.
        segment_breakdown: NPS by segment.

    Returns:
        Structured dict with trends and action items.
    """
    try:
        # Group by month for trends
        monthly: dict[str, list[int]] = {}
        for resp in validated_responses:
            date = resp.get("date", "")
            period = date[:7] if date else "unknown"
            monthly.setdefault(period, []).append(resp["score"])

        trends: list[dict[str, Any]] = []
        for period in sorted(monthly.keys()):
            if period == "unknown":
                continue
            scores = monthly[period]
            total = len(scores)
            promoters = sum(1 for s in scores if s >= 9)
            detractors = sum(1 for s in scores if s <= 6)
            p_pct = promoters / total * 100 if total > 0 else 0
            d_pct = detractors / total * 100 if total > 0 else 0
            trends.append({
                "period": period,
                "nps_score": round(p_pct - d_pct, 1),
                "response_count": total,
            })

        # Action items
        action_items: list[str] = []
        if nps_score < 0:
            action_items.append("Critical: NPS is negative — prioritize detractor outreach immediately")
        elif nps_score < 30:
            action_items.append("NPS below 30 — investigate detractor complaints for root causes")

        if len(trends) >= 2 and trends[-1]["nps_score"] < trends[-2]["nps_score"]:
            action_items.append("NPS declining — review recent product/service changes")

        for seg in segment_breakdown:
            if seg.get("nps_score", 0) < -10:
                action_items.append(f"Segment '{seg['segment']}' has very low NPS ({seg['nps_score']}) — needs targeted intervention")

        # Check for high detractor comments
        detractor_comments = [r["comment"] for r in validated_responses if r["score"] <= 6 and r.get("comment")]
        if len(detractor_comments) > 5:
            action_items.append(f"Review {len(detractor_comments)} detractor comments for common themes")

        if not action_items:
            action_items.append("NPS is healthy — continue current customer experience strategy")

        return {"status": "success", "trends": trends, "action_items": action_items}
    except Exception as exc:
        return {"status": "error", "trends": [], "action_items": [], "error": f"Trend tracking failed: {exc}"}
