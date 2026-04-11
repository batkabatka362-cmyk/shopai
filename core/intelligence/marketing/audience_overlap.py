"""Audience overlap detection — bidding against yourself wastes 20-40% budget."""
from __future__ import annotations

from typing import Any


def _calculate_overlap(camp_a: dict, camp_b: dict) -> dict[str, Any]:
    """Estimate audience overlap between two campaigns."""
    interests_a = set(camp_a.get("interests", []))
    interests_b = set(camp_b.get("interests", []))
    age_a = camp_a.get("age_range", (18, 65))
    age_b = camp_b.get("age_range", (18, 65))

    interest_overlap = len(interests_a & interests_b) / max(len(interests_a | interests_b), 1) * 100 if interests_a or interests_b else 50
    age_overlap = max(0, min(age_a[1], age_b[1]) - max(age_a[0], age_b[0])) / max(age_a[1] - age_a[0], 1) * 100

    overlap_pct = round((interest_overlap + age_overlap) / 2, 1)

    return {
        "campaign_a": camp_a.get("name", camp_a.get("id", "?")),
        "campaign_b": camp_b.get("name", camp_b.get("id", "?")),
        "overlap_pct": overlap_pct,
        "action": "Consolidate or exclude" if overlap_pct > 50 else "Monitor",
    }


def detect_audience_overlap(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect audience overlap between ad sets — bidding against yourself wastes 20-40% budget.

    Checks for similar targeting across active campaigns.
    """
    active = [c for c in campaigns if isinstance(c, dict) and c.get("status") == "active"]
    if len(active) < 2:
        return {"status": "insufficient_campaigns", "note": "Need 2+ active campaigns to check overlap"}

    overlaps = []
    for i, camp_a in enumerate(active):
        for camp_b in active[i + 1:]:
            overlap = _calculate_overlap(camp_a, camp_b)
            if overlap["overlap_pct"] > 30:
                overlaps.append(overlap)

    return {
        "overlapping_pairs": len(overlaps),
        "details": overlaps,
        "estimated_budget_waste": f"{min(len(overlaps) * 15, 40)}%" if overlaps else "0%",
        "recommendation": (
            f"Consolidate {len(overlaps)} overlapping ad sets to reduce self-competition"
            if overlaps else "No significant audience overlap detected"
        ),
    }
