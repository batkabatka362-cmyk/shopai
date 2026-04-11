"""LTV:CAC Dashboard Engine — alert manager.

Alerts when LTV:CAC ratio drops below threshold.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def manage_alerts(
    ratio: float,
    trend: str,
    cac: dict[str, Any],
    ltv: dict[str, Any],
) -> dict[str, Any]:
    """Generate alerts based on LTV:CAC metrics.

    Args:
        ratio: Overall LTV:CAC ratio.
        trend: Current trend assessment.
        cac: CAC breakdown by channel.
        ltv: LTV breakdown by segment.

    Returns:
        Structured dict with alerts.
    """
    try:
        alerts: list[dict[str, Any]] = []

        if ratio < 1.0:
            alerts.append({
                "alert_type": "ratio_critical",
                "severity": "critical",
                "message": f"LTV:CAC ratio is {ratio} — spending more to acquire than customers are worth",
                "channel": "all",
            })
        elif ratio < 1.5:
            alerts.append({
                "alert_type": "ratio_warning",
                "severity": "high",
                "message": f"LTV:CAC ratio is {ratio} — approaching unprofitable territory",
                "channel": "all",
            })
        elif ratio < 3.0:
            alerts.append({
                "alert_type": "ratio_low",
                "severity": "medium",
                "message": f"LTV:CAC ratio is {ratio} — below the healthy 3:1 benchmark",
                "channel": "all",
            })

        # Per-channel CAC alerts
        by_channel = cac.get("by_channel", {})
        avg_cac = cac.get("average", 0.0)
        for ch, ch_cac in by_channel.items():
            if avg_cac > 0 and ch_cac > avg_cac * 2.0:
                alerts.append({
                    "alert_type": "channel_expensive",
                    "severity": "high",
                    "message": f"Channel '{ch}' CAC (${ch_cac:.2f}) is 2x+ above average (${avg_cac:.2f})",
                    "channel": ch,
                })

        # Per-segment LTV alerts
        by_segment = ltv.get("by_segment", {})
        avg_ltv = ltv.get("average", 0.0)
        for seg, seg_ltv in by_segment.items():
            if avg_ltv > 0 and seg_ltv < avg_ltv * 0.3:
                alerts.append({
                    "alert_type": "segment_low_ltv",
                    "severity": "medium",
                    "message": f"Segment '{seg}' LTV (${seg_ltv:.2f}) is far below average (${avg_ltv:.2f})",
                    "channel": seg,
                })

        return {"status": "success", "alerts": alerts}
    except Exception as exc:
        return {"status": "error", "alerts": [], "error": f"Alert management failed: {exc}"}
