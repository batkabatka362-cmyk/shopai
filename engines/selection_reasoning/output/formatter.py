"""Selection Reasoning Engine — output formatting.

Assembles the results from all five reasoning modules into a single,
structured reasoning report with narrative, citations, risk disclosure,
alternatives, and action plan.
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
    """Format the combined results of all reasoning modules.

    Args:
        engine_name: Name of this engine.
        results: Dict of module_name -> module output contract.
        data: The original validated input data.
        elapsed: Total pipeline duration in seconds.

    Returns:
        Formatted engine contract: {status, data, meta, error}
    """
    # Extract results from each module
    narrative = results.get("narrative", {}).get("data", {})
    citations = results.get("citations", {}).get("data", {})
    risk_disclosure = results.get("risk_disclosure", {}).get("data", {})
    alternatives = results.get("alternatives", {}).get("data", {})
    action_plan = results.get("action_plan", {}).get("data", {})

    # Determine overall status
    has_errors = any(
        r.get("status") == "error"
        for r in results.values()
        if isinstance(r, dict)
    )

    # Narrative is the critical module — if it fails, the report is incomplete
    narrative_ok = results.get("narrative", {}).get("status") == "success"
    overall_status = "success" if narrative_ok else ("partial" if not has_errors else "fail")

    # Build the executive summary
    executive_summary = _build_executive_summary(
        narrative, citations, risk_disclosure, data,
    )

    # Compute report confidence from module validations
    module_validities = []
    for mod_result in results.values():
        if isinstance(mod_result, dict):
            mod_data = mod_result.get("data", {})
            if isinstance(mod_data, dict):
                validation = mod_data.get("validation", {})
                if isinstance(validation, dict):
                    module_validities.append(validation.get("valid", True))

    validity_ratio = (
        sum(1 for v in module_validities if v) / len(module_validities)
        if module_validities else 0.5
    )
    confidence_score = min(1.0, validity_ratio)

    selected = data.get("selected_product", {})

    return {
        "status": overall_status,
        "data": {
            "executive_summary": executive_summary,
            "narrative": {
                "summary": narrative.get("summary", ""),
                "explanation": narrative.get("explanation", {}),
                "key_points": narrative.get("key_points", []),
                "full_narrative": narrative.get("full_narrative", ""),
                "word_count": narrative.get("word_count", 0),
            },
            "citations": {
                "formatted": citations.get("citations", []),
                "total": citations.get("total_citations", 0),
                "sources": citations.get("sources_represented", []),
            },
            "risk_disclosure": {
                "risks": risk_disclosure.get("risks", []),
                "worst_case": risk_disclosure.get("worst_case", {}),
                "summary": risk_disclosure.get("risk_summary", ""),
                "severity_counts": risk_disclosure.get("severity_counts", {}),
            },
            "alternatives": {
                "alternatives": alternatives.get("alternatives", []),
                "close_seconds": alternatives.get("close_seconds", []),
                "total_evaluated": alternatives.get("total_candidates_evaluated", 0),
            },
            "action_plan": {
                "steps": action_plan.get("steps", []),
                "timeline": action_plan.get("timeline", {}),
                "budget": action_plan.get("budget", {}),
                "milestones": action_plan.get("milestones", []),
            },
            "selected_product": {
                "product_id": selected.get("product_id", ""),
                "product_name": selected.get("product_name", ""),
                "unified_score": selected.get("unified_score", 0),
            },
            "module_results": {
                name: {
                    "status": r.get("status"),
                    "has_data": r.get("data") is not None,
                }
                for name, r in results.items()
                if isinstance(r, dict)
            },
        },
        "meta": {
            "engine": engine_name,
            "confidence": round(confidence_score, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
            "goal": data.get("goal", "balanced"),
            "investment": data.get("investment", 0),
            "modules_run": list(results.keys()),
            "modules_succeeded": sum(
                1 for r in results.values()
                if isinstance(r, dict) and r.get("status") == "success"
            ),
        },
        "error": None if overall_status == "success" else {
            "reason": "One or more reasoning modules failed",
            "failed_modules": [
                name for name, r in results.items()
                if isinstance(r, dict) and r.get("status") == "error"
            ],
        },
    }


def _build_executive_summary(
    narrative: dict[str, Any],
    citations: dict[str, Any],
    risk_disclosure: dict[str, Any],
    data: dict[str, Any],
) -> str:
    """Build a concise executive summary combining key outputs."""
    parts: list[str] = []

    # Lead with the narrative summary
    summary = narrative.get("summary", "")
    if summary:
        parts.append(summary)

    # Add risk headline
    risk_summary = risk_disclosure.get("risk_summary", "")
    if risk_summary:
        parts.append(risk_summary)

    # Add citation count
    total_citations = citations.get("total_citations", 0)
    if total_citations > 0:
        parts.append(f"Backed by {total_citations} data citations from {len(citations.get('sources_represented', []))} engine sources.")

    # Add investment context
    investment = data.get("investment", 0)
    if investment > 0:
        parts.append(f"Investment basis: ${investment:,.0f}.")

    return " ".join(parts)
