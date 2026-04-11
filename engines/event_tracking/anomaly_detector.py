"""Event Tracking Engine — anomaly detector.

Detects unusual event patterns: volume spikes, drop-offs,
unexpected event types, and timing anomalies.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Anomaly thresholds
# ---------------------------------------------------------------------------

_SPIKE_THRESHOLD = 3.0    # 3x above expected
_DROP_THRESHOLD = 0.3     # 70% below expected
_MIN_EVENTS_FOR_ANALYSIS = 5


def detect_anomalies(
    event_groups: list[dict[str, Any]],
    categorized: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect anomalies in event patterns.

    Args:
        event_groups: Grouped events from collector.
        categorized: Categorized events.

    Returns:
        Structured dict with detected anomalies.
    """
    try:
        groups = copy.deepcopy(event_groups)

        if not groups:
            return {
                "status": "success",
                "anomalies": [],
                "total_anomalies": 0,
            }

        anomalies: list[dict[str, Any]] = []

        # Calculate expected volume (average across types)
        counts = [g.get("count", 0) for g in groups]
        if not counts:
            return {
                "status": "success",
                "anomalies": [],
                "total_anomalies": 0,
            }

        avg_count = sum(counts) / len(counts)

        for group in groups:
            etype = group.get("event_type", "unknown")
            count = group.get("count", 0)

            if avg_count < _MIN_EVENTS_FOR_ANALYSIS:
                continue

            ratio = count / avg_count if avg_count > 0 else 0

            # Volume spike
            if ratio > _SPIKE_THRESHOLD:
                deviation = round((ratio - 1.0) * 100, 1)
                anomalies.append({
                    "event_type": etype,
                    "anomaly_type": "volume_spike",
                    "severity": "high" if ratio > _SPIKE_THRESHOLD * 2 else "medium",
                    "expected_value": round(avg_count, 1),
                    "actual_value": float(count),
                    "deviation_pct": deviation,
                })

            # Volume drop
            elif ratio < _DROP_THRESHOLD and count > 0:
                deviation = round((1.0 - ratio) * -100, 1)
                anomalies.append({
                    "event_type": etype,
                    "anomaly_type": "volume_drop",
                    "severity": "medium",
                    "expected_value": round(avg_count, 1),
                    "actual_value": float(count),
                    "deviation_pct": deviation,
                })

        # Check for zero-count types (missing events)
        for group in groups:
            if group.get("count", 0) == 0:
                anomalies.append({
                    "event_type": group.get("event_type", "unknown"),
                    "anomaly_type": "missing_events",
                    "severity": "high",
                    "expected_value": round(avg_count, 1),
                    "actual_value": 0.0,
                    "deviation_pct": -100.0,
                })

        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2}
        anomalies.sort(key=lambda a: severity_order.get(a["severity"], 3))

        return {
            "status": "success",
            "anomalies": anomalies,
            "total_anomalies": len(anomalies),
        }
    except Exception as exc:
        return {
            "status": "error",
            "anomalies": [],
            "error": f"Anomaly detection failed: {exc}",
        }
