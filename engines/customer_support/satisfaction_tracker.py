"""Customer Support Engine — satisfaction tracker.

Track customer satisfaction from ticket sentiment and resolution data.
"""
from __future__ import annotations

import copy
from typing import Any


def track_satisfaction(
    **kwargs: Any,
) -> dict[str, Any]:
    """Track customer satisfaction.

    Args:
        **kwargs: Must include all prior stage data.

    Returns:
        Structured dict with satisfaction scores.
    """
    try:
        class_data = kwargs.get("ticket_classifier_data", {})
        res_data = kwargs.get("resolution_finder_data", {})
        work_data = kwargs.get("workload_analyzer_data", {})

        classified = class_data.get("classified_tickets", [])
        resolutions = res_data.get("suggested_resolutions", [])
        workload = work_data.get("workload_report", {})

        # Sentiment-based satisfaction
        sentiment_counts = {"positive": 0, "neutral": 0, "negative": 0}
        for t in classified:
            s = t.get("sentiment", "neutral")
            sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

        total = len(classified) or 1
        satisfaction_score = round(
            (sentiment_counts["positive"] * 1.0 + sentiment_counts["neutral"] * 0.6) / total, 2
        )

        # Resolution confidence average
        res_confidences = [float(r.get("confidence", 0)) for r in resolutions]
        avg_confidence = round(sum(res_confidences) / max(len(res_confidences), 1), 2)

        # Overall CSAT estimate
        csat = round((satisfaction_score * 0.6 + avg_confidence * 0.4) * 100, 1)

        return {
            "status": "success",
            "result": {
                "classified_tickets": classified,
                "suggested_resolutions": resolutions,
                "workload_report": workload,
                "satisfaction_scores": {
                    "csat_estimate": csat,
                    "sentiment_distribution": sentiment_counts,
                    "satisfaction_score": satisfaction_score,
                    "avg_resolution_confidence": avg_confidence,
                },
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Satisfaction tracking failed: {exc}"}
