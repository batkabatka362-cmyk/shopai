"""Order Quality Engine — quality scorer.

Scores quality per supplier based on defect rates and severity.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any

_SEVERITY_WEIGHTS = {"low": 1, "medium": 3, "high": 5, "critical": 10}


def score_quality(
    defect_rates: list[dict[str, Any]],
    defects: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score supplier quality based on defects.

    Args:
        defect_rates: Defect rates from defect_tracker.
        defects: Raw defect records.
        suppliers: Supplier list.
        orders: Order list.

    Returns:
        Structured dict with supplier quality scores.
    """
    try:
        # Map orders to suppliers
        order_supplier: dict[str, str] = {}
        for order in orders:
            oid = str(order.get("id", order.get("order_id", "")))
            sid = str(order.get("supplier_id", ""))
            if sid:
                order_supplier[oid] = sid

        # Severity breakdown per supplier
        sup_severity: dict[str, dict[str, int]] = {}
        for defect in defects:
            oid = str(defect.get("order_id", ""))
            sid = order_supplier.get(oid, "unknown")
            severity = str(defect.get("severity", "medium")).lower()
            sup_severity.setdefault(sid, {}).setdefault(severity, 0)
            sup_severity[sid][severity] += 1

        # Score each supplier
        supplier_rates = {
            r["entity"]: r["defect_rate"]
            for r in defect_rates if r["entity_type"] == "supplier"
        }
        sup_map = {str(s.get("id", "")): s for s in suppliers}

        scores: list[dict[str, Any]] = []
        for sup in suppliers:
            sid = str(sup.get("id", ""))
            name = str(sup.get("name", ""))
            defect_rate = 0.0

            # Find defect rate
            for r in defect_rates:
                if r["entity_type"] == "supplier" and (r["entity"] == name or r["entity"] == sid):
                    defect_rate = r["defect_rate"]
                    break

            severity = sup_severity.get(sid, {})
            weighted_score = sum(
                count * _SEVERITY_WEIGHTS.get(sev, 1)
                for sev, count in severity.items()
            )

            # Quality score: 100 - penalty (higher is better)
            penalty = min(weighted_score * 2.0 + defect_rate * 100, 100)
            quality_score = round(max(0, 100 - penalty), 1)

            if quality_score >= 90:
                grade = "A"
            elif quality_score >= 75:
                grade = "B"
            elif quality_score >= 60:
                grade = "C"
            elif quality_score >= 40:
                grade = "D"
            else:
                grade = "F"

            scores.append({
                "supplier_id": sid,
                "supplier_name": name,
                "quality_score": quality_score,
                "defect_rate": defect_rate,
                "severity_breakdown": severity,
                "grade": grade,
            })

        scores.sort(key=lambda s: s["quality_score"], reverse=True)

        return {"status": "success", "supplier_quality_scores": scores}
    except Exception as exc:
        return {"status": "error", "supplier_quality_scores": [], "error": f"Quality scoring failed: {exc}"}
