"""Feedback Processing Engine — action recommender.

Recommends concrete actions based on categorized feedback, priorities,
and spotted trends.
"""
from __future__ import annotations

import copy
from typing import Any


_ACTION_TEMPLATES: dict[str, str] = {
    "product_quality": "Investigate and resolve product quality issues in category '{theme}'",
    "shipping": "Review shipping processes related to '{theme}'",
    "customer_service": "Improve customer service training for '{theme}' scenarios",
    "pricing": "Evaluate pricing strategy considering '{theme}' feedback",
    "usability": "Conduct UX review to address '{theme}' concerns",
    "feature_request": "Evaluate feature request: '{theme}'",
    "other": "Review feedback cluster around '{theme}'",
}


def recommend_actions(
    categorized: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    trends: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend actions based on feedback analysis.

    Args:
        categorized: Categorized feedback items.
        priorities: Priority-scored feedback items.
        trends: Spotted trends.

    Returns:
        Structured dict with recommended actions.
    """
    try:
        priority_map: dict[str, dict[str, Any]] = {}
        for p in priorities:
            priority_map[str(p.get("id", ""))] = p

        # Group categorized items by (category, theme)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in copy.deepcopy(categorized):
            key = (str(item.get("category", "other")), str(item.get("theme", "general")))
            if key not in groups:
                groups[key] = []
            groups[key].append(item)

        actions: list[dict[str, Any]] = []

        for (category, theme), items in groups.items():
            if len(items) < 1:
                continue

            # Determine priority from constituent items
            scores = []
            for item in items:
                p = priority_map.get(str(item.get("id", "")), {})
                scores.append(float(p.get("priority_score", 0.3)))
            avg_score = sum(scores) / len(scores) if scores else 0.3

            template = _ACTION_TEMPLATES.get(category, _ACTION_TEMPLATES["other"])
            action_text = template.format(theme=theme)

            # Check if this theme is trending
            trend_match = next(
                (t for t in trends if t.get("theme") == theme), None,
            )
            if trend_match and trend_match.get("direction") == "rising":
                avg_score = min(avg_score + 0.1, 1.0)

            priority_label = _score_to_priority(avg_score)
            impact = _estimate_impact(len(items), avg_score)

            actions.append({
                "action": action_text,
                "priority": priority_label,
                "category": category,
                "supporting_feedback_count": len(items),
                "expected_impact": impact,
            })

        actions.sort(
            key=lambda x: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(x["priority"], 0),
            reverse=True,
        )

        return {
            "status": "success",
            "recommended_actions": actions,
        }
    except Exception as exc:
        return {
            "status": "error",
            "recommended_actions": [],
            "error": f"Action recommendation failed: {exc}",
        }


def _score_to_priority(score: float) -> str:
    """Convert numeric score to priority label."""
    if score >= 0.8:
        return "critical"
    if score >= 0.6:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def _estimate_impact(count: int, score: float) -> str:
    """Estimate expected impact from action."""
    combined = count * 0.3 + score * 0.7
    if combined >= 3.0:
        return "high"
    if combined >= 1.5:
        return "medium"
    return "low"
