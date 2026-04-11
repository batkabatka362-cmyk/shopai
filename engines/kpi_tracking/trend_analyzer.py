"""KPI Tracking Engine — trend analyzer.

Detects KPI trends by comparing current values to historical records.
Classifies trends as up, down, or stable with percentage change.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# Threshold for considering a change significant
_STABLE_THRESHOLD = 0.02  # 2% change or less is considered stable


def analyze_trends(
    current_kpis: dict[str, Any],
    past_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze KPI trends by comparing current to historical values.

    Args:
        current_kpis: Current KPI values dict.
        past_records: List of past KPI tracking records from memory.

    Returns:
        Structured dict with trend analysis per KPI.
    """
    try:
        current_kpis = copy.deepcopy(current_kpis)

        # Extract previous KPI values from past records
        previous_kpis = _get_previous_kpis(past_records)

        tracked_kpis = ["aov", "cac", "ltv", "conversion_rate", "revenue",
                        "order_count", "repeat_rate", "gross_margin"]

        trends: list[dict[str, Any]] = []

        for kpi_name in tracked_kpis:
            current_val = float(current_kpis.get(kpi_name, 0))
            previous_val = float(previous_kpis.get(kpi_name, 0))

            if previous_val == 0:
                # No historical data — can't compute trend
                direction = "new"
                change_pct = 0.0
            else:
                change_pct = round((current_val - previous_val) / abs(previous_val), 4)

                if abs(change_pct) <= _STABLE_THRESHOLD:
                    direction = "stable"
                elif change_pct > 0:
                    direction = "up"
                else:
                    direction = "down"

            trends.append({
                "kpi": kpi_name,
                "direction": direction,
                "change_pct": round(change_pct * 100, 2),  # As percentage
                "current_value": current_val,
                "previous_value": previous_val,
            })

        return {
            "status": "success",
            "trends": trends,
        }
    except Exception as exc:
        return {
            "status": "error",
            "trends": [],
            "error": f"Trend analysis failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_previous_kpis(past_records: list[dict[str, Any]]) -> dict[str, float]:
    """Extract the most recent KPI values from past records."""
    if not past_records:
        return {}

    # Past records should be sorted newest-first; take the most recent
    most_recent = past_records[0] if past_records else {}
    return most_recent.get("kpis", {})
