"""Event Tracking Engine — event categorizer.

Categorizes events into business domains: commerce, engagement,
system, lifecycle. Assigns priority levels.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Category mappings
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "purchase": ("commerce", "transaction"),
    "add_to_cart": ("commerce", "cart"),
    "checkout_start": ("commerce", "checkout"),
    "checkout_complete": ("commerce", "checkout"),
    "refund": ("commerce", "transaction"),
    "page_view": ("engagement", "browsing"),
    "click": ("engagement", "interaction"),
    "search": ("engagement", "discovery"),
    "signup": ("lifecycle", "acquisition"),
    "login": ("lifecycle", "authentication"),
    "unsubscribe": ("lifecycle", "churn"),
    "error": ("system", "error"),
    "timeout": ("system", "performance"),
    "api_call": ("system", "integration"),
}

_PRIORITY_MAP: dict[str, str] = {
    "commerce": "high",
    "lifecycle": "high",
    "engagement": "medium",
    "system": "low",
}


def categorize_events(
    event_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Categorize grouped events into business domains.

    Args:
        event_groups: List of EventGroup dicts.

    Returns:
        Structured dict with categorized events.
    """
    try:
        groups = copy.deepcopy(event_groups)
        categorized: list[dict[str, Any]] = []

        category_counts: dict[str, int] = {}

        for group in groups:
            etype = group.get("event_type", "unknown")
            count = group.get("count", 0)

            cat, subcat = _CATEGORY_MAP.get(etype, ("other", "uncategorized"))
            priority = _PRIORITY_MAP.get(cat, "low")

            category_counts[cat] = category_counts.get(cat, 0) + count

            categorized.append({
                "event_type": etype,
                "category": cat,
                "subcategory": subcat,
                "count": count,
                "priority": priority,
            })

        return {
            "status": "success",
            "categorized": categorized,
            "category_counts": category_counts,
            "total_categorized": len(categorized),
        }
    except Exception as exc:
        return {
            "status": "error",
            "categorized": [],
            "error": f"Event categorization failed: {exc}",
        }
