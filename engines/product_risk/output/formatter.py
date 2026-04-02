"""Product Risk Engine — output formatting.

Assembles module results into a unified risk report with composite score,
risk classification, top risks, and actionable recommendations.
"""
from __future__ import annotations

import time
from typing import Any

ENGINE_NAME = "product_risk"

RISK_LABELS: dict[str, str] = {
    "low": "Low Risk — proceed with standard precautions",
    "moderate": "Moderate Risk — address identified concerns before scaling",
    "elevated": "Elevated Risk — significant mitigation needed",
    "high": "High Risk — proceed only with strong risk controls",
    "critical": "Critical Risk — consider alternative products",
}


def format_output(
    engine_name: str,
    module_results: dict[str, Any],
    composite_score: float,
    risk_classification: str,
    top_risks: list[dict[str, Any]],
    data: dict[str, Any],
    elapsed: float,
) -> dict[str, Any]:
    """Format the complete risk assessment output.

    Combines all module results into a single coherent report following
    the engine contract: {status, data, meta, error}.
    """
    category = data.get("category", "unknown")
    label = RISK_LABELS.get(risk_classification, "Unknown classification")

    # Build per-module summaries
    module_summaries = _build_module_summaries(module_results)

    # Generate recommendations from top risks
    recommendations = _generate_recommendations(top_risks, risk_classification)

    # Count modules that ran successfully
    successful = sum(
        1 for r in module_results.values() if r.get("status") == "success"
    )
    total = len(module_results)

    summary = (
        f"Product risk assessment for '{category}': {risk_classification.upper()} "
        f"(score {composite_score:.2f}). {label}. "
        f"{successful}/{total} modules completed successfully."
    )

    return {
        "status": "success",
        "data": {
            "summary": summary,
            "composite_risk_score": composite_score,
            "risk_classification": risk_classification,
            "risk_label": label,
            "top_risks": top_risks,
            "recommendations": recommendations,
            "module_results": module_results,
            "module_summaries": module_summaries,
        },
        "meta": {
            "engine": engine_name,
            "category": category,
            "confidence": _compute_confidence(successful, total),
            "modules_run": total,
            "modules_succeeded": successful,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
        },
        "error": None,
    }


def _build_module_summaries(
    module_results: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract a compact summary from each module result."""
    summaries: dict[str, dict[str, Any]] = {}
    for name, result in module_results.items():
        if result.get("status") != "success":
            summaries[name] = {
                "status": result.get("status", "error"),
                "error": result.get("error", "Unknown error"),
            }
            continue

        rdata = result.get("data") or {}
        summaries[name] = {
            "status": "success",
            "risk_level": rdata.get("risk_level", "unknown"),
            "risk_score": rdata.get(
                "composite_risk_score", rdata.get("risk_score", None)
            ),
            "classification": rdata.get("classification", None),
        }
    return summaries


def _generate_recommendations(
    top_risks: list[dict[str, Any]],
    classification: str,
) -> list[str]:
    """Generate actionable recommendations based on top risks."""
    recs: list[str] = []

    if classification in ("high", "critical"):
        recs.append(
            "Conduct a detailed risk mitigation review before committing capital."
        )

    for risk in top_risks:
        module = risk.get("module", "")
        severity = risk.get("severity", "")

        if module == "seasonal_risk" and severity in ("high", "extreme"):
            recs.append(
                "Build cash reserves to cover 4+ months of off-season expenses."
            )
        elif module == "market_risk" and severity in ("high", "extreme"):
            recs.append(
                "Validate market demand with a small test batch before full launch."
            )
        elif module == "supplier_risk" and severity in ("high", "extreme"):
            recs.append(
                "Diversify suppliers — single-source dependency is critical risk."
            )
        elif module == "legal_risk" and severity in ("high", "extreme"):
            recs.append(
                "Obtain legal review for regulatory and IP compliance."
            )
        elif module == "financial_risk" and severity in ("high", "extreme"):
            recs.append(
                "Reassess pricing and cost structure — margins may be unsustainable."
            )

    if not recs:
        recs.append("Risk levels are manageable. Proceed with standard due diligence.")

    return recs


def _compute_confidence(successful: int, total: int) -> float:
    """Confidence score based on how many modules completed."""
    if total == 0:
        return 0.0
    return round(successful / total, 2)
