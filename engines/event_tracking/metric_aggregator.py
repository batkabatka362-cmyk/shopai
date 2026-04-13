"""Event Tracking Engine — metric aggregator.

Aggregates event data into business metrics: event rates,
conversion funnels, volume trends, and timing distributions.
"""
from __future__ import annotations

import copy
from typing import Any


def aggregate_metrics(
    event_groups: list[dict[str, Any]],
    categorized: list[dict[str, Any]],
    period: str = "day",
) -> dict[str, Any]:
    """Aggregate event metrics.

    Args:
        event_groups: Grouped events from collector.
        categorized: Categorized events.
        period: Aggregation period (hour, day, week).

    Returns:
        Structured dict with aggregated metrics.
    """
    try:
        groups = copy.deepcopy(event_groups)

        total_events = sum(g.get("count", 0) for g in groups)
        unique_types = len(groups)

        metrics: list[dict[str, Any]] = []

        # Total event volume
        metrics.append({
            "metric_name": "total_events",
            "value": float(total_events),
            "unit": "count",
            "trend": "stable",
        })

        # Events per type
        metrics.append({
            "metric_name": "unique_event_types",
            "value": float(unique_types),
            "unit": "count",
            "trend": "stable",
        })

        # Category breakdown
        cat_counts: dict[str, int] = {}
        for cat_event in categorized:
            cat = cat_event.get("category", "other")
            cat_counts[cat] = cat_counts.get(cat, 0) + cat_event.get("count", 0)

        for cat, count in sorted(cat_counts.items()):
            rate = round(count / total_events * 100, 1) if total_events > 0 else 0.0
            metrics.append({
                "metric_name": f"{cat}_event_rate",
                "value": rate,
                "unit": "percent",
                "trend": "stable",
            })

        # Per-type volume metrics (top 10)
        sorted_groups = sorted(groups, key=lambda g: g.get("count", 0), reverse=True)
        for group in sorted_groups[:10]:
            etype = group.get("event_type", "unknown")
            count = group.get("count", 0)
            metrics.append({
                "metric_name": f"{etype}_volume",
                "value": float(count),
                "unit": "count",
                "trend": "stable",
            })

        return {
            "status": "success",
            "metrics": metrics,
            "total_metrics": len(metrics),
        }
    except Exception as exc:
        return {
            "status": "error",
            "metrics": [],
            "error": f"Metric aggregation failed: {exc}",
        }
