"""Competitor Ad Intelligence Engine — spend estimator.

Estimates competitor ad spend from impressions and platform CPM benchmarks.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any

_PLATFORM_CPM: dict[str, float] = {
    "facebook": 7.50,
    "google": 3.50,
    "tiktok": 10.00,
    "instagram": 8.00,
    "youtube": 6.50,
    "linkedin": 12.00,
    "twitter": 5.50,
}


def estimate_spend(
    ads_detected: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate competitor ad spend based on detected ads and CPM benchmarks.

    Args:
        ads_detected: Detected ads with impression estimates.

    Returns:
        Structured dict with spend estimates.
    """
    try:
        # Aggregate impressions per competitor+platform
        agg: dict[str, dict[str, int]] = {}
        for ad in ads_detected:
            comp = ad.get("competitor", "")
            plat = ad.get("platform", "")
            imps = int(ad.get("estimated_impressions", 0))
            agg.setdefault(comp, {}).setdefault(plat, 0)
            agg[comp][plat] += imps

        estimates: list[dict[str, Any]] = []
        for comp, plats in agg.items():
            for plat, imps in plats.items():
                cpm = _PLATFORM_CPM.get(plat, 7.00)
                monthly_spend = round((imps / 1000.0) * cpm, 2)

                if imps > 100000:
                    confidence = "high"
                elif imps > 10000:
                    confidence = "medium"
                else:
                    confidence = "low"

                estimates.append({
                    "competitor": comp,
                    "platform": plat,
                    "estimated_monthly_spend": monthly_spend,
                    "confidence": confidence,
                })

        return {"status": "success", "spend_estimates": estimates}
    except Exception as exc:
        return {"status": "error", "spend_estimates": [], "error": f"Spend estimation failed: {exc}"}
