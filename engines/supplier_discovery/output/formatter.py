"""Supplier Discovery Engine — output formatting."""
from __future__ import annotations

import time
from typing import Any


def format_output(engine_name: str, results: dict[str, Any], data: dict[str, Any], elapsed: float) -> dict[str, Any]:
    confidence = _compute_confidence(results)
    summary = _generate_summary(results, data)

    return {
        "status": "success",
        "data": {
            "product_type": data.get("product_type", ""),
            "summary": summary,
            "sources": results.get("sources", {}),
            "scored_suppliers": results.get("scored_suppliers", []),
            "moq_analysis": results.get("moq_analysis", {}),
            "lead_time": results.get("lead_time", {}),
            "negotiation": results.get("negotiation", {}),
        },
        "meta": {
            "engine": engine_name,
            "confidence": confidence,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
            "modules_run": 5,
        },
        "error": None,
    }


def _compute_confidence(results: dict[str, Any]) -> float:
    scores = []
    sources = results.get("sources", {})
    if sources.get("status") == "success":
        scores.append(sources.get("meta", {}).get("confidence", 0.5))
    moq = results.get("moq_analysis", {})
    if moq.get("status") == "success":
        scores.append(moq.get("meta", {}).get("confidence", 0.5))
    lt = results.get("lead_time", {})
    if lt.get("status") == "success":
        scores.append(lt.get("meta", {}).get("confidence", 0.5))
    neg = results.get("negotiation", {})
    if neg.get("status") == "success":
        scores.append(neg.get("meta", {}).get("confidence", 0.5))
    return round(sum(scores) / max(len(scores), 1), 2) if scores else 0.3


def _generate_summary(results: dict[str, Any], data: dict[str, Any]) -> str:
    parts = [f"Supplier Discovery: {data.get('product_type', '?')}"]
    sources = results.get("sources", {})
    if sources.get("status") == "success":
        top = sources.get("data", {}).get("top_recommendation", {})
        if top:
            parts.append(f"Best source: {top.get('name', '?')} (margin ~{top.get('estimated_margin_pct', 0)}%)")
    moq = results.get("moq_analysis", {})
    if moq.get("status") == "success":
        moq_data = moq.get("data", {})
        parts.append(f"MOQ investment: ${moq_data.get('total_investment', 0):,.0f}")
    lt = results.get("lead_time", {})
    if lt.get("status") == "success":
        lt_data = lt.get("data", {})
        parts.append(f"Lead time: {lt_data.get('total_days', {}).get('typical', '?')} days")
    return ". ".join(parts)
