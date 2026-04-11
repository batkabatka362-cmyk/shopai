"""Supplier Engine — negotiation advisor.

Advise on negotiation strategy based on supplier performance and risk.
"""
from __future__ import annotations

import copy
from typing import Any


def advise_negotiation(
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate negotiation advice per supplier.

    Args:
        **kwargs: Must include performance and risk data.

    Returns:
        Structured dict with negotiation tips.
    """
    try:
        perf_data = kwargs.get("performance_scorer_data", {})
        risk_data = kwargs.get("risk_assessor_data", {})
        scores = perf_data.get("scores", [])
        risks = risk_data.get("risks", [])
        risk_map = {r["supplier_id"]: r for r in risks}

        tips: list[dict[str, Any]] = []

        for score in scores:
            sid = score.get("supplier_id", "unknown")
            overall = float(score.get("overall", 0.5))
            risk = risk_map.get(sid, {})
            risk_level = risk.get("risk_level", "medium")

            advice: list[str] = []
            leverage = "neutral"

            if overall >= 0.8:
                advice.append("Strong performer — negotiate long-term contract for volume discount")
                leverage = "partnership"
            elif overall >= 0.6:
                advice.append("Good performer — push for improved delivery terms")
                leverage = "balanced"
            else:
                advice.append("Underperformer — negotiate penalty clauses or seek alternatives")
                leverage = "buyer_advantage"

            if risk_level == "high":
                advice.append("High risk — diversify supply chain before committing")
            if score.get("delivery_score", 1.0) < 0.8:
                advice.append("Push for guaranteed delivery SLAs")
            if score.get("cost_score", 1.0) < 0.5:
                advice.append("Request competitive pricing or volume breaks")

            tips.append({
                "supplier_id": sid,
                "leverage": leverage,
                "advice": advice,
            })

        return {
            "status": "success",
            "result": {"negotiation_tips": tips},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Negotiation advice failed: {exc}"}
