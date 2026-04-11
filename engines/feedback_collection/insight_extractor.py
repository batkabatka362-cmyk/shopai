"""Feedback Collection Engine — insight extractor.

Extracts actionable insights from parsed feedback:
priority issues, improvement areas, and positive reinforcement.
"""
from __future__ import annotations

import copy
from typing import Any


def extract_insights(
    sentiment_summary: dict[str, Any],
    feedback: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract actionable insights from feedback.

    Args:
        sentiment_summary: Parsed sentiment data.
        feedback: Aggregated feedback.

    Returns:
        Structured dict with insights and action items.
    """
    try:
        summary = copy.deepcopy(sentiment_summary)
        insights: list[dict[str, Any]] = []
        action_items: list[str] = []

        negative_pct = float(summary.get("negative_pct", 0))
        positive_pct = float(summary.get("positive_pct", 0))
        avg_rating = float(summary.get("avg_rating", 0))
        themes = summary.get("themes", {})

        # Overall sentiment insight
        if negative_pct > 30:
            insights.append({
                "insight": f"High negative sentiment ({negative_pct}%) — investigate common complaints",
                "category": "sentiment",
                "frequency": int(summary.get("negative", 0)),
                "sentiment": "negative",
            })
            action_items.append("Review and address top negative feedback themes urgently")
        elif positive_pct > 70:
            insights.append({
                "insight": f"Strong positive sentiment ({positive_pct}%) — leverage for marketing",
                "category": "sentiment",
                "frequency": int(summary.get("positive", 0)),
                "sentiment": "positive",
            })
            action_items.append("Use positive feedback quotes in marketing materials")

        # Rating insight
        if avg_rating > 0:
            if avg_rating < 3.0:
                insights.append({
                    "insight": f"Average rating {avg_rating}/5 is below benchmark — needs improvement",
                    "category": "rating",
                    "frequency": 0,
                    "sentiment": "negative",
                })
                action_items.append("Investigate root causes of low ratings")
            elif avg_rating >= 4.0:
                insights.append({
                    "insight": f"Average rating {avg_rating}/5 is excellent — maintain standards",
                    "category": "rating",
                    "frequency": 0,
                    "sentiment": "positive",
                })

        # Theme-based insights
        sorted_themes = sorted(themes.items(), key=lambda x: x[1], reverse=True)
        for theme, count in sorted_themes[:5]:
            if count >= 3:
                insights.append({
                    "insight": f"'{theme}' mentioned {count} times — significant feedback theme",
                    "category": theme,
                    "frequency": count,
                    "sentiment": "neutral",
                })

                if theme == "shipping" and negative_pct > 20:
                    action_items.append("Review shipping times and carrier performance")
                elif theme == "quality" and negative_pct > 20:
                    action_items.append("Audit product quality and supplier standards")
                elif theme == "price":
                    action_items.append("Evaluate pricing strategy against customer expectations")
                elif theme == "service":
                    action_items.append("Review customer service response times and training")

        if not action_items:
            action_items.append("Continue monitoring feedback — no urgent actions needed")

        return {
            "status": "success",
            "insights": insights,
            "action_items": action_items,
            "total_insights": len(insights),
        }
    except Exception as exc:
        return {
            "status": "error",
            "insights": [],
            "action_items": [],
            "error": f"Insight extraction failed: {exc}",
        }
