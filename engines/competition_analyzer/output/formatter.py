"""Competition Analyzer — output formatting."""
from __future__ import annotations
import time
from typing import Any

def format_output(engine_name: str, results: dict[str, Any], data: dict[str, Any], elapsed: float) -> dict[str, Any]:
    comp = results.get("competitors", {}).get("data") or {}
    pricing = results.get("pricing", {}).get("data") or {}
    reviews = results.get("reviews", {}).get("data") or {}

    summary_parts = [f"Competition Analysis: {data.get('category', '?')}"]
    if comp.get("total_competitors"):
        summary_parts.append(f"{comp['total_competitors']} competitors found")
    if comp.get("landscape"):
        summary_parts.append(f"Landscape: {comp['landscape']}")

    return {
        "status": "success",
        "data": {
            "summary": ". ".join(summary_parts),
            "competitors": results.get("competitors", {}),
            "pricing": results.get("pricing", {}),
            "reviews": results.get("reviews", {}),
            "differentiation": results.get("differentiation", {}),
            "positioning": results.get("positioning", {}),
        },
        "meta": {"engine": engine_name, "confidence": 0.75, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_seconds": round(elapsed, 3)},
        "error": None,
    }
