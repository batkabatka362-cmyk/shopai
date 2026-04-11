"""Performance Monitor Engine — uptime tracker.

Tracks store uptime and downtime periods. Computes uptime percentage
and identifies downtime patterns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Uptime thresholds
# ---------------------------------------------------------------------------

_EXCELLENT_UPTIME = 0.999    # 99.9%
_GOOD_UPTIME = 0.995         # 99.5%
_ACCEPTABLE_UPTIME = 0.99    # 99.0%


def track_uptime(
    uptime_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track store uptime from monitoring data.

    Computes overall uptime percentage, identifies downtime windows,
    and rates reliability.

    Args:
        uptime_data: List of check dicts with timestamp, status (up/down),
            response_time_ms, check_interval_seconds fields.

    Returns:
        Structured dict with uptime_pct and downtime_windows.
    """
    try:
        checks = copy.deepcopy(uptime_data)

        if not checks:
            return {
                "status": "success",
                "uptime_pct": 100.0,
                "downtime_windows": [],
                "total_checks": 0,
                "rating": "no_data",
            }

        # Sort by timestamp
        checks.sort(key=lambda c: float(c.get("timestamp", 0)))

        total_checks = len(checks)
        up_count = 0
        down_count = 0
        downtime_windows: list[dict[str, Any]] = []
        current_down_start = None
        current_down_checks = 0

        for check in checks:
            status = str(check.get("status", "up")).lower()
            timestamp = float(check.get("timestamp", 0))

            if status == "up":
                up_count += 1
                if current_down_start is not None:
                    # End of downtime window
                    downtime_windows.append({
                        "start_timestamp": current_down_start,
                        "end_timestamp": timestamp,
                        "duration_seconds": round(timestamp - current_down_start, 1),
                        "checks_down": current_down_checks,
                    })
                    current_down_start = None
                    current_down_checks = 0
            else:
                down_count += 1
                if current_down_start is None:
                    current_down_start = timestamp
                current_down_checks += 1

        # Handle ongoing downtime
        if current_down_start is not None:
            last_ts = float(checks[-1].get("timestamp", 0))
            downtime_windows.append({
                "start_timestamp": current_down_start,
                "end_timestamp": last_ts,
                "duration_seconds": round(last_ts - current_down_start, 1),
                "checks_down": current_down_checks,
                "ongoing": True,
            })

        uptime_pct = round(up_count / total_checks, 6) if total_checks > 0 else 1.0
        total_downtime_seconds = sum(
            w.get("duration_seconds", 0) for w in downtime_windows
        )

        # Rating
        if uptime_pct >= _EXCELLENT_UPTIME:
            rating = "excellent"
        elif uptime_pct >= _GOOD_UPTIME:
            rating = "good"
        elif uptime_pct >= _ACCEPTABLE_UPTIME:
            rating = "acceptable"
        else:
            rating = "poor"

        return {
            "status": "success",
            "uptime_pct": round(uptime_pct * 100, 4),
            "downtime_windows": downtime_windows,
            "total_checks": total_checks,
            "up_checks": up_count,
            "down_checks": down_count,
            "total_downtime_seconds": round(total_downtime_seconds, 1),
            "rating": rating,
        }
    except Exception as exc:
        return {
            "status": "error",
            "uptime_pct": 0.0,
            "downtime_windows": [],
            "error": f"Uptime tracking failed: {exc}",
        }
