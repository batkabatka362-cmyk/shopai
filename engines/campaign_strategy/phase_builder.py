"""Campaign Strategy Engine — phase builder.

Builds campaign phases: awareness, consideration, conversion, retention.
"""
from __future__ import annotations

from typing import Any


def build_phases(
    duration_days: int,
    channels: list[str],
    goal: str,
) -> dict[str, Any]:
    """Build campaign phases with channel assignments."""
    try:
        phases: list[dict[str, Any]] = []

        # Phase allocation based on duration
        if duration_days <= 14:
            phase_split = [
                ("awareness", 0.3, ["awareness", "engagement"]),
                ("conversion", 0.7, ["conversion", "urgency"]),
            ]
        elif duration_days <= 30:
            phase_split = [
                ("awareness", 0.25, ["awareness"]),
                ("consideration", 0.35, ["engagement", "education"]),
                ("conversion", 0.40, ["conversion", "urgency"]),
            ]
        else:
            phase_split = [
                ("awareness", 0.20, ["awareness"]),
                ("consideration", 0.25, ["engagement", "education"]),
                ("conversion", 0.35, ["conversion", "urgency"]),
                ("retention", 0.20, ["retention", "loyalty"]),
            ]

        awareness_channels = [c for c in channels if c in ("social_media", "display_ads", "influencer", "content")]
        conversion_channels = [c for c in channels if c in ("email", "search_ads", "sms", "affiliate")]
        all_channels = channels

        for name, pct, goals in phase_split:
            days = max(int(duration_days * pct), 1)
            if name == "awareness":
                phase_channels = awareness_channels or all_channels[:2]
            elif name in ("conversion", "retention"):
                phase_channels = conversion_channels or all_channels[-2:]
            else:
                phase_channels = all_channels

            kpis = []
            if name == "awareness":
                kpis = ["reach", "impressions", "brand_awareness_lift"]
            elif name == "consideration":
                kpis = ["click_through_rate", "engagement_rate", "site_visits"]
            elif name == "conversion":
                kpis = ["conversion_rate", "cost_per_acquisition", "roas"]
            elif name == "retention":
                kpis = ["repeat_purchase_rate", "customer_satisfaction", "ltv"]

            phases.append({
                "name": name,
                "duration_days": days,
                "channels": phase_channels,
                "budget_pct": round(pct * 100, 1),
                "goal": goals[0] if goals else name,
                "kpis": kpis,
            })

        return {"status": "success", "phases": phases}
    except Exception as exc:
        return {"status": "error", "phases": [], "error": f"Phase building failed: {exc}"}
