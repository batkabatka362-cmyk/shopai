"""Campaign Strategy Engine — channel planner.

Plans channel mix based on audience demographics and budget constraints.
"""
from __future__ import annotations

import copy
from typing import Any

_CHANNEL_PROFILES = {
    "email": {"cost_per_reach": 0.01, "conversion_rate": 0.035, "role": "retention_conversion"},
    "social_media": {"cost_per_reach": 0.05, "conversion_rate": 0.012, "role": "awareness_engagement"},
    "search_ads": {"cost_per_reach": 0.15, "conversion_rate": 0.045, "role": "intent_capture"},
    "display_ads": {"cost_per_reach": 0.03, "conversion_rate": 0.005, "role": "awareness"},
    "influencer": {"cost_per_reach": 0.08, "conversion_rate": 0.025, "role": "trust_building"},
    "content": {"cost_per_reach": 0.02, "conversion_rate": 0.015, "role": "education_seo"},
    "sms": {"cost_per_reach": 0.02, "conversion_rate": 0.04, "role": "urgency_conversion"},
    "affiliate": {"cost_per_reach": 0.10, "conversion_rate": 0.03, "role": "performance"},
}


def plan_channels(
    channels: list[str],
    budget: float,
    audience: dict[str, Any],
) -> dict[str, Any]:
    """Plan channel mix and allocate budget percentages."""
    try:
        audience_size = int(audience.get("size", 10000))

        channel_plans: list[dict[str, Any]] = []
        total_weight = 0.0
        weights: dict[str, float] = {}

        for ch in channels:
            profile = _CHANNEL_PROFILES.get(ch, {"cost_per_reach": 0.05, "conversion_rate": 0.01, "role": "general"})
            # Weight by conversion rate (higher conversion = more budget)
            weight = profile["conversion_rate"] * 100
            weights[ch] = weight
            total_weight += weight

        for ch in channels:
            profile = _CHANNEL_PROFILES.get(ch, {"cost_per_reach": 0.05, "conversion_rate": 0.01, "role": "general"})
            budget_pct = round(weights.get(ch, 1) / max(total_weight, 1) * 100, 1)
            ch_budget = budget * budget_pct / 100
            cpr = profile["cost_per_reach"]
            expected_reach = int(ch_budget / max(cpr, 0.001))
            expected_conversions = int(expected_reach * profile["conversion_rate"])

            channel_plans.append({
                "channel": ch,
                "role": profile["role"],
                "budget_pct": budget_pct,
                "expected_reach": min(expected_reach, audience_size * 3),
                "expected_conversions": expected_conversions,
            })

        return {"status": "success", "channel_plans": channel_plans}
    except Exception as exc:
        return {"status": "error", "channel_plans": [], "error": f"Channel planning failed: {exc}"}
