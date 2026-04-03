"""Supplier Engine — relationship tracker.

Track supplier relationship health over time.
"""
from __future__ import annotations

import copy
from typing import Any


def track_relationships(
    **kwargs: Any,
) -> dict[str, Any]:
    """Track relationship health per supplier.

    Args:
        **kwargs: Must include performance, risk, and negotiation data.

    Returns:
        Structured dict with relationship health summary.
    """
    try:
        perf_data = kwargs.get("performance_scorer_data", {})
        risk_data = kwargs.get("risk_assessor_data", {})
        neg_data = kwargs.get("negotiation_advisor_data", {})

        scores = perf_data.get("scores", [])
        risks = risk_data.get("risks", [])
        risk_map = {r["supplier_id"]: r for r in risks}
        neg_map = {t["supplier_id"]: t for t in neg_data.get("negotiation_tips", [])}

        health_scores: list[dict[str, Any]] = []
        total_health = 0.0

        for score in scores:
            sid = score.get("supplier_id", "unknown")
            overall = float(score.get("overall", 0.5))
            risk = risk_map.get(sid, {})
            risk_score = float(risk.get("risk_score", 0.5))

            # Relationship health = performance weighted minus risk
            health = round(overall * 0.7 + (1 - risk_score) * 0.3, 2)
            total_health += health

            status = "healthy" if health >= 0.7 else "at_risk" if health >= 0.4 else "critical"

            health_scores.append({
                "supplier_id": sid,
                "health_score": health,
                "status": status,
                "performance": overall,
                "risk": risk_score,
            })

        n = len(health_scores)
        avg_health = round(total_health / max(n, 1), 2)

        return {
            "status": "success",
            "result": {
                "scores": [
                    {**h, **{"negotiation_tips": neg_map.get(h["supplier_id"], {}).get("advice", [])}}
                    for h in health_scores
                ],
                "negotiation_tips": neg_data.get("negotiation_tips", []),
                "relationship_health": {
                    "average_health": avg_health,
                    "total_suppliers": n,
                    "healthy": sum(1 for h in health_scores if h["status"] == "healthy"),
                    "at_risk": sum(1 for h in health_scores if h["status"] == "at_risk"),
                    "critical": sum(1 for h in health_scores if h["status"] == "critical"),
                },
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Relationship tracking failed: {exc}"}
