"""Selection Decision Engine — output formatting.

Assembles the results from all pipeline modules into a single,
structured output contract with summary, details, and metadata.
"""
from __future__ import annotations

import time
from typing import Any


def format_output(
    engine_name: str,
    results: dict[str, Any],
    data: dict[str, Any],
    elapsed: float,
) -> dict[str, Any]:
    """Format the combined results of all selection modules.

    Args:
        engine_name: Name of this engine.
        results: Dict of module_name -> module output contract.
        data: The original validated input data.
        elapsed: Total pipeline duration in seconds.

    Returns:
        Formatted engine contract: {status, data, meta, error}
    """
    # Extract key results from each module
    final = results.get("final_selector", {}).get("data", {})
    confidence = results.get("confidence", {}).get("data", {})
    comparison = results.get("comparison", {}).get("data", {})
    ranking = results.get("ranking", {}).get("data", {})
    aggregation = results.get("score_aggregator", {}).get("data", {})

    # Selected product summary
    selected = final.get("selected_product", {})
    backup = final.get("backup_product", {})
    confidence_info = final.get("confidence_at_selection", {})

    # Determine overall status
    has_errors = any(
        r.get("status") == "error"
        for r in results.values()
        if isinstance(r, dict)
    )
    # Final selector is the critical module
    final_ok = results.get("final_selector", {}).get("status") == "success"
    overall_status = "success" if final_ok else ("partial" if not has_errors else "fail")

    # Build human-readable summary
    summary = _build_summary(selected, backup, confidence_info, data)

    # Compute overall confidence
    composite_confidence = confidence.get("composite_confidence", 0)
    confidence_pct = min(1.0, composite_confidence / 100.0)

    return {
        "status": overall_status,
        "data": {
            "summary": summary,
            "selected_product": selected,
            "backup_product": backup,
            "decision_rationale": final.get("decision_rationale", {}),
            "action_plan": final.get("action_plan", {}),
            "expected_outcome": final.get("expected_outcome", {}),
            "confidence": confidence,
            "comparison": comparison,
            "ranking": ranking,
            "aggregation": aggregation.get("aggregation_summary", {}),
            "module_results": {
                name: {"status": r.get("status"), "has_data": r.get("data") is not None}
                for name, r in results.items()
                if isinstance(r, dict)
            },
        },
        "meta": {
            "engine": engine_name,
            "confidence": round(confidence_pct, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
            "products_evaluated": len(data.get("products", [])),
            "goal": data.get("goal", "balanced"),
            "modules_run": list(results.keys()),
        },
        "error": None if overall_status == "success" else {
            "reason": "One or more modules failed",
            "failed_modules": [
                name for name, r in results.items()
                if isinstance(r, dict) and r.get("status") == "error"
            ],
        },
    }


def _build_summary(
    selected: dict[str, Any],
    backup: dict[str, Any],
    confidence_info: dict[str, Any],
    data: dict[str, Any],
) -> str:
    """Build a human-readable one-line summary of the selection decision."""
    parts: list[str] = []

    pid = selected.get("product_id", "unknown")
    score = selected.get("unified_score", 0)
    conf_level = confidence_info.get("level", "unknown")
    conf_score = confidence_info.get("score", 0)
    goal = data.get("goal", "balanced")

    parts.append(f"Selected: {pid} (score {score:.1f}/100)")
    parts.append(f"Confidence: {conf_level} ({conf_score:.0f}%)")
    parts.append(f"Goal: {goal}")

    backup_id = backup.get("product_id")
    if backup_id:
        parts.append(f"Backup: {backup_id}")

    total = len(data.get("products", []))
    parts.append(f"Evaluated: {total} products")

    return " | ".join(parts)
