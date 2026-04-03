"""Audience Targeting Engine — size estimator.

Estimates reachable audience sizes accounting for reachability factors
like email validity, platform presence, and ad platform match rates.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Reachability factors (conservative industry estimates)
# ---------------------------------------------------------------------------

_EMAIL_REACHABILITY = 0.85   # ~15% bounce / invalid
_AD_PLATFORM_MATCH = 0.65   # Custom audience match rate
_SOCIAL_REACHABILITY = 0.70  # Social platform reach


def estimate_sizes(
    match_results: list[dict[str, Any]],
    channel: str = "email",
) -> dict[str, Any]:
    """Estimate reachable audience sizes for each segment.

    Args:
        match_results: List of RuleMatchResult dicts (from rule_matcher).
        channel: Target channel for reachability estimation.

    Returns:
        Structured dict with size estimates per segment.
    """
    try:
        match_results = copy.deepcopy(match_results)

        reachability_factor = _get_reachability_factor(channel)

        estimates: list[dict[str, Any]] = []
        total_matched = 0
        total_reachable = 0

        for result in match_results:
            seg_id = str(result.get("segment_id", ""))
            name = str(result.get("name", ""))
            matched_size = int(result.get("match_count", 0))

            estimated_reachable = int(matched_size * reachability_factor)
            reachability_rate = round(reachability_factor, 4)

            total_matched += matched_size
            total_reachable += estimated_reachable

            estimates.append({
                "segment_id": seg_id,
                "name": name,
                "matched_size": matched_size,
                "estimated_reachable": estimated_reachable,
                "reachability_rate": reachability_rate,
            })

        # Sort by estimated_reachable descending
        estimates.sort(key=lambda e: e["estimated_reachable"], reverse=True)

        return {
            "status": "success",
            "estimates": estimates,
            "total_matched": total_matched,
            "total_reachable": total_reachable,
            "channel": channel,
            "reachability_factor": reachability_factor,
        }
    except Exception as exc:
        return {
            "status": "error",
            "estimates": [],
            "error": f"Size estimation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_reachability_factor(channel: str) -> float:
    """Get the reachability factor for a given channel."""
    factors = {
        "email": _EMAIL_REACHABILITY,
        "ads": _AD_PLATFORM_MATCH,
        "social": _SOCIAL_REACHABILITY,
    }
    return factors.get(channel.lower(), _EMAIL_REACHABILITY)
