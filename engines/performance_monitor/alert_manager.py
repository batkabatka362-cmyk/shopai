"""Performance Monitor Engine — alert manager.

Generates alerts when performance degrades beyond configured thresholds.
Supports page-level and store-wide alerts.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_alerts(
    performance_scores: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]],
    uptime_pct: float,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Generate performance alerts based on thresholds.

    Checks page scores, bottleneck severity, and uptime against
    user-defined thresholds and generates actionable alerts.

    Args:
        performance_scores: Per-page scores from speed_analyzer.
        bottlenecks: Detected bottlenecks from bottleneck_finder.
        uptime_pct: Uptime percentage from uptime_tracker.
        thresholds: User-defined thresholds with min_score, min_uptime,
            max_load_time_ms fields.

    Returns:
        Structured dict with alerts list and recommendations.
    """
    try:
        scores = copy.deepcopy(performance_scores)
        bnecks = copy.deepcopy(bottlenecks)
        thresh = copy.deepcopy(thresholds)

        min_score = float(thresh.get("min_score", 70))
        min_uptime = float(thresh.get("min_uptime", 99.5))
        max_load_ms = float(thresh.get("max_load_time_ms", 4000))

        alerts: list[dict[str, Any]] = []
        recommendations: list[str] = []

        # --- Page score alerts ---
        for page in scores:
            url = str(page.get("url", ""))
            score = float(page.get("score", 0))
            avg_load = float(page.get("avg_load_time_ms", 0))
            rating = str(page.get("rating", ""))

            if rating == "no_data":
                continue

            if score < min_score:
                alerts.append({
                    "alert_type": "low_performance_score",
                    "severity": "critical" if score < 40 else "high" if score < 60 else "medium",
                    "url": url,
                    "message": (
                        f"Page '{url}' performance score is {score}/100 "
                        f"(threshold: {min_score})."
                    ),
                })

            if avg_load > max_load_ms:
                alerts.append({
                    "alert_type": "slow_page_load",
                    "severity": "high" if avg_load > max_load_ms * 1.5 else "medium",
                    "url": url,
                    "message": (
                        f"Page '{url}' load time is {round(avg_load)}ms "
                        f"(threshold: {round(max_load_ms)}ms)."
                    ),
                })

        # --- Uptime alert ---
        if uptime_pct < min_uptime:
            alerts.append({
                "alert_type": "uptime_below_threshold",
                "severity": "critical" if uptime_pct < 99.0 else "high",
                "url": "store-wide",
                "message": (
                    f"Store uptime is {uptime_pct}% "
                    f"(threshold: {min_uptime}%)."
                ),
            })

        # --- Bottleneck alerts ---
        critical_bottlenecks = [
            b for b in bnecks if b.get("severity") in ("critical", "high")
        ]
        if critical_bottlenecks:
            alerts.append({
                "alert_type": "critical_bottlenecks",
                "severity": "high",
                "url": "store-wide",
                "message": (
                    f"{len(critical_bottlenecks)} critical/high-severity "
                    f"performance bottlenecks detected."
                ),
            })

        # --- Generate recommendations ---
        poor_pages = [p for p in scores if p.get("rating") == "poor"]
        if poor_pages:
            recommendations.append(
                f"Prioritize optimization of {len(poor_pages)} poor-performing pages.",
            )

        server_bottlenecks = [
            b for b in bnecks if b.get("type") == "slow_server_response"
        ]
        if server_bottlenecks:
            recommendations.append(
                "Enable server-side caching and optimize database queries.",
            )

        render_bottlenecks = [
            b for b in bnecks if b.get("type") == "render_blocking"
        ]
        if render_bottlenecks:
            recommendations.append(
                "Defer non-critical CSS/JS and implement code splitting.",
            )

        if uptime_pct < 99.9:
            recommendations.append(
                "Review infrastructure redundancy and failover configuration.",
            )

        # Sort alerts by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        alerts.sort(
            key=lambda a: severity_order.get(a.get("severity", "low"), 4),
        )

        return {
            "status": "success",
            "alerts": alerts,
            "recommendations": recommendations,
            "total_alerts": len(alerts),
        }
    except Exception as exc:
        return {
            "status": "error",
            "alerts": [],
            "recommendations": [],
            "error": f"Alert management failed: {exc}",
        }
