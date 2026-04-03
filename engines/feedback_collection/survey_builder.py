"""Feedback Collection Engine — survey builder.

Builds feedback surveys: question templates, rating scales,
NPS questions, and channel-appropriate formats.
"""
from __future__ import annotations

import copy
from typing import Any


def build_surveys(
    feedback_sources: list[dict[str, Any]],
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Build survey templates for feedback collection.

    Args:
        feedback_sources: Configured feedback sources/channels.
        filters: Filters for survey targeting.

    Returns:
        Structured dict with survey configurations.
    """
    try:
        sources = copy.deepcopy(feedback_sources)
        surveys: list[dict[str, Any]] = []

        for source in sources:
            channel = str(source.get("channel", source.get("type", "general")))
            name = str(source.get("name", channel))

            # Build channel-appropriate survey
            questions: list[dict[str, Any]] = []

            # NPS question (universal)
            questions.append({
                "type": "nps",
                "text": "How likely are you to recommend us? (0-10)",
                "scale": [0, 10],
                "required": True,
            })

            # Satisfaction question
            questions.append({
                "type": "rating",
                "text": "How satisfied are you with your experience?",
                "scale": [1, 5],
                "required": True,
            })

            # Channel-specific questions
            if channel in ("email", "post_purchase"):
                questions.append({
                    "type": "open_text",
                    "text": "What could we improve about your purchase experience?",
                    "required": False,
                })
            elif channel in ("support", "ticket"):
                questions.append({
                    "type": "rating",
                    "text": "How quickly was your issue resolved?",
                    "scale": [1, 5],
                    "required": True,
                })
            elif channel in ("product", "review"):
                questions.append({
                    "type": "rating",
                    "text": "Rate the product quality",
                    "scale": [1, 5],
                    "required": True,
                })

            surveys.append({
                "source": name,
                "channel": channel,
                "questions": questions,
                "question_count": len(questions),
            })

        return {
            "status": "success",
            "surveys": surveys,
            "total_surveys": len(surveys),
        }
    except Exception as exc:
        return {
            "status": "error",
            "surveys": [],
            "error": f"Survey building failed: {exc}",
        }
