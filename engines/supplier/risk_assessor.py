"""Supplier Engine — risk assessor.

Assess supplier risk based on concentration, geography, and performance history.
"""
from __future__ import annotations

import copy
from typing import Any


def assess_risk(
    **kwargs: Any,
) -> dict[str, Any]:
    """Assess supplier risk.

    Args:
        **kwargs: Must include suppliers and performance_scorer_data.

    Returns:
        Structured dict with risk assessment per supplier.
    """
    try:
        suppliers = copy.deepcopy(kwargs.get("suppliers", []))
        perf_data = kwargs.get("performance_scorer_data", {})
        perf_scores = perf_data.get("scores", [])
        perf_map = {s["supplier_id"]: s for s in perf_scores}

        total_suppliers = len(suppliers)
        risks: list[dict[str, Any]] = []

        for sup in suppliers:
            sid = str(sup.get("id", "unknown"))
            perf = perf_map.get(sid, {})
            overall_score = float(perf.get("overall", 0.5))

            risk_factors: list[str] = []
            risk_score = 0.0

            # Performance risk
            if overall_score < 0.5:
                risk_factors.append("Low performance score")
                risk_score += 0.3
            elif overall_score < 0.7:
                risk_factors.append("Moderate performance")
                risk_score += 0.1

            # Single-source risk
            if total_suppliers <= 1:
                risk_factors.append("Single source dependency")
                risk_score += 0.4

            # Geography risk
            region = sup.get("region", "unknown")
            if region in ("unknown", ""):
                risk_factors.append("Unknown region")
                risk_score += 0.1

            risk_score = round(min(risk_score, 1.0), 2)
            risk_level = "low" if risk_score < 0.3 else "medium" if risk_score < 0.6 else "high"

            risks.append({
                "supplier_id": sid,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_factors": risk_factors,
            })

        return {
            "status": "success",
            "result": {"risks": risks},
        }
    except Exception as exc:
        return {"status": "error", "error": f"Risk assessment failed: {exc}"}
