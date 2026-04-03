"""Feedback Processing Engine — categorizer.

Categorizes each feedback item by type and theme using keyword matching
and content analysis.
"""
from __future__ import annotations

import copy
from typing import Any


_DEFAULT_CATEGORIES = [
    "product_quality", "shipping", "customer_service",
    "pricing", "usability", "feature_request", "other",
]

_KEYWORD_MAP: dict[str, list[str]] = {
    "product_quality": ["quality", "defect", "broken", "damaged", "durable", "material"],
    "shipping": ["shipping", "delivery", "late", "package", "tracking", "arrived"],
    "customer_service": ["support", "service", "agent", "response", "helpful", "rude"],
    "pricing": ["price", "expensive", "cheap", "cost", "value", "worth", "overpriced"],
    "usability": ["easy", "difficult", "confusing", "intuitive", "interface", "ux"],
    "feature_request": ["wish", "want", "feature", "add", "missing", "need", "should"],
}


def categorize_feedback(
    feedback: list[dict[str, Any]],
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Categorize feedback items by type and theme.

    Args:
        feedback: List of feedback item dicts.
        categories: Allowed categories (defaults to built-in list).

    Returns:
        Structured dict with categorized feedback.
    """
    try:
        items = copy.deepcopy(feedback)
        allowed = categories if categories else _DEFAULT_CATEGORIES
        categorized: list[dict[str, Any]] = []

        for item in items:
            fid = str(item.get("id", ""))
            content = str(item.get("content", "")).lower()
            tags = [str(t).lower() for t in item.get("tags", [])]

            best_cat = "other"
            best_score = 0.0

            for cat, keywords in _KEYWORD_MAP.items():
                if cat not in allowed:
                    continue
                hits = sum(1 for kw in keywords if kw in content or kw in tags)
                score = hits / len(keywords) if keywords else 0.0
                if score > best_score:
                    best_score = score
                    best_cat = cat

            theme = _extract_theme(content)

            categorized.append({
                "id": fid,
                "content": str(item.get("content", "")),
                "category": best_cat,
                "theme": theme,
                "confidence": round(min(best_score * 2.0, 1.0), 2),
            })

        return {
            "status": "success",
            "categorized": categorized,
            "category_distribution": _count_categories(categorized),
        }
    except Exception as exc:
        return {
            "status": "error",
            "categorized": [],
            "error": f"Categorization failed: {exc}",
        }


def _extract_theme(content: str) -> str:
    """Extract a simple theme label from content."""
    if any(w in content for w in ["return", "refund", "exchange"]):
        return "returns_and_refunds"
    if any(w in content for w in ["slow", "late", "delay"]):
        return "delays"
    if any(w in content for w in ["love", "great", "excellent", "amazing"]):
        return "positive_experience"
    if any(w in content for w in ["bad", "terrible", "worst", "horrible"]):
        return "negative_experience"
    if any(w in content for w in ["improve", "better", "suggest"]):
        return "improvement_suggestion"
    return "general"


def _count_categories(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count items per category."""
    counts: dict[str, int] = {}
    for item in items:
        cat = item.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return counts
