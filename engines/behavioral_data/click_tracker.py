"""Behavioral Data Engine — click tracker.

Tracks clicks, views, and interactions per product.
Computes click-through rates and view-to-action ratios.
"""
from __future__ import annotations

import copy
from typing import Any


def track_clicks(
    events: list[dict[str, Any]],
    product_views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track click and view events per product.

    Args:
        events: List of user interaction events.
        product_views: List of product view events.

    Returns:
        Structured dict with click summaries per product.
    """
    try:
        all_events = copy.deepcopy(events)
        views = copy.deepcopy(product_views)

        # Aggregate views per product
        view_counts: dict[str, int] = {}
        for view in views:
            pid = str(view.get("product_id", "unknown"))
            view_counts[pid] = view_counts.get(pid, 0) + 1

        # Aggregate clicks per product from events
        click_counts: dict[str, int] = {}
        for event in all_events:
            if event.get("type") in ("click", "add_to_cart", "buy"):
                pid = str(event.get("product_id", "unknown"))
                click_counts[pid] = click_counts.get(pid, 0) + 1

        # Build summaries
        all_products = set(view_counts.keys()) | set(click_counts.keys())
        summaries: list[dict[str, Any]] = []

        for pid in sorted(all_products):
            v = view_counts.get(pid, 0)
            c = click_counts.get(pid, 0)
            ctr = round(c / v, 4) if v > 0 else 0.0

            summaries.append({
                "product_id": pid,
                "clicks": c,
                "views": v,
                "click_through_rate": ctr,
            })

        # Sort by views descending
        summaries.sort(key=lambda s: s["views"], reverse=True)

        return {
            "status": "success",
            "summaries": summaries,
            "total_products": len(summaries),
            "total_views": sum(view_counts.values()),
            "total_clicks": sum(click_counts.values()),
        }
    except Exception as exc:
        return {
            "status": "error",
            "summaries": [],
            "error": f"Click tracking failed: {exc}",
        }
