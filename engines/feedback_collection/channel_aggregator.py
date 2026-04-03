"""Feedback Collection Engine — channel aggregator.

Aggregates feedback from multiple channels into a unified
format: reviews, surveys, support tickets, social mentions.
"""
from __future__ import annotations

import copy
from typing import Any


def aggregate_channels(
    feedback_sources: list[dict[str, Any]],
    period: str = "30d",
) -> dict[str, Any]:
    """Aggregate feedback from all configured channels.

    Args:
        feedback_sources: Feedback source configs with data.
        period: Time period for aggregation.

    Returns:
        Structured dict with aggregated feedback.
    """
    try:
        sources = copy.deepcopy(feedback_sources)
        feedback: list[dict[str, Any]] = []
        total_responses = 0

        for source in sources:
            name = str(source.get("name", source.get("channel", "unknown")))
            responses = source.get("responses", source.get("data", []))

            if not isinstance(responses, list):
                responses = []

            feedback.append({
                "source": name,
                "responses": responses,
                "count": len(responses),
            })
            total_responses += len(responses)

        return {
            "status": "success",
            "feedback": feedback,
            "total_responses": total_responses,
            "total_sources": len(feedback),
        }
    except Exception as exc:
        return {
            "status": "error",
            "feedback": [],
            "error": f"Channel aggregation failed: {exc}",
        }
