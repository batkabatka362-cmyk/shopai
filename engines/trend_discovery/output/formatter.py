"""Trend Discovery Engine — output formatting."""
from __future__ import annotations
import time
from typing import Any

def format_output(engine_name: str, results: dict[str, Any], category: str, elapsed: float) -> dict[str, Any]:
    composite = results.get("composite", {})
    composite_data = composite.get("data", {}) if composite.get("status") == "success" else {}

    confidence = composite.get("meta", {}).get("confidence", 0.5) if composite.get("status") == "success" else 0.3
    classification = composite_data.get("classification", "unknown")
    action = composite_data.get("action", "monitor")

    summary = _build_summary(results, category, classification, action)

    return {
        "status": "success",
        "data": {
            "category": category,
            "composite": composite_data,
            "search": results.get("search", {}).get("data", {}),
            "social": results.get("social", {}).get("data", {}),
            "marketplace": results.get("marketplace", {}).get("data", {}),
            "emerging": results.get("emerging", {}).get("data", {}),
            "summary": summary,
            "action": action,
        },
        "meta": {"engine": engine_name, "confidence": confidence, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
        "error": None,
    }

def _build_summary(results: dict[str, Any], category: str, classification: str, action: str) -> str:
    parts = [f"Trend Discovery Report: {category}"]
    if classification and classification != "unknown":
        parts.append(f"Overall trend: {classification}.")
    parts.append(f"Recommended action: {action}.")
    search = results.get("search", {}).get("data", {})
    if search.get("trending_count", 0) > 0:
        parts.append(f"Search: {search['trending_count']} trending keywords found.")
    emerging = results.get("emerging", {}).get("data", {})
    if emerging.get("total_evaluated", 0) > 0:
        parts.append(f"Emerging niches: {emerging['total_evaluated']} evaluated.")
    return " ".join(parts)
