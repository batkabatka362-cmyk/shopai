"""Cohort Analysis Engine — LTV projector.

Projects lifetime value by cohort using historical revenue patterns.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from typing import Any


def project_ltv(
    cohort_retention: list[dict[str, Any]],
    cohort_revenues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project lifetime value per cohort.

    Args:
        cohort_retention: Retention data per cohort.
        cohort_revenues: Revenue data per cohort.

    Returns:
        Structured dict with LTV projections and trends.
    """
    try:
        rev_map = {r["period"]: r["revenue"] for r in cohort_revenues}
        projections: list[dict[str, Any]] = []
        best_cohort = ""
        best_ltv = 0.0

        for cohort in cohort_retention:
            period = cohort["period"]
            size = cohort.get("size", 1)
            revenue = rev_map.get(period, 0.0)
            retention_rates = cohort.get("retention_rates", [])

            # Revenue per customer
            rpc = revenue / size if size > 0 else 0.0

            # Project forward using retention decay
            projected_ltv = rpc
            if len(retention_rates) >= 2:
                last_rate = retention_rates[-1]
                decay = retention_rates[-1] / retention_rates[-2] if retention_rates[-2] > 0 else 0.5
                decay = max(0.1, min(decay, 0.99))

                # Project 12 more periods
                current_rate = last_rate
                for _ in range(12):
                    current_rate *= decay
                    if current_rate < 0.01:
                        break
                    projected_ltv += rpc * current_rate

            projected_ltv = round(projected_ltv, 2)

            if projected_ltv > best_ltv:
                best_ltv = projected_ltv
                best_cohort = period

            projections.append({
                "period": period,
                "size": size,
                "revenue": revenue,
                "ltv": projected_ltv,
                "retention_rates": retention_rates,
            })

        # Trends
        ltvs = [p["ltv"] for p in projections]
        if len(ltvs) >= 2:
            if ltvs[-1] > ltvs[0] * 1.05:
                trend_direction = "improving"
            elif ltvs[-1] < ltvs[0] * 0.95:
                trend_direction = "declining"
            else:
                trend_direction = "stable"
        else:
            trend_direction = "insufficient_data"

        trends = {
            "direction": trend_direction,
            "avg_ltv": round(sum(ltvs) / len(ltvs), 2) if ltvs else 0.0,
            "best_ltv": best_ltv,
            "worst_ltv": round(min(ltvs), 2) if ltvs else 0.0,
        }

        return {
            "status": "success",
            "projections": projections,
            "best_cohort": best_cohort,
            "trends": trends,
        }
    except Exception as exc:
        return {"status": "error", "projections": [], "best_cohort": "", "trends": {}, "error": f"LTV projection failed: {exc}"}
