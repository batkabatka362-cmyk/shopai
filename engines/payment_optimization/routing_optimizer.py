"""Payment Optimization Engine — routing optimizer.

Recommends optimal payment routing to minimize processing fees
by comparing processor fee schedules.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def optimize_routing(
    fee_analyses: list[dict[str, Any]],
    fees: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Optimize payment routing.

    Args:
        fee_analyses: Per-method fee analysis results.
        fees: Fee schedules from processors.
        transactions: List of transaction dicts.

    Returns:
        Structured dict with routing recommendations.
    """
    try:
        # Find current processor per method
        method_processors: dict[str, dict[str, float]] = {}
        for txn in transactions:
            method = str(txn.get("payment_method", "unknown"))
            processor = str(txn.get("processor", "unknown"))
            amount = float(txn.get("amount", 0.0))
            fee = float(txn.get("fee", 0.0))

            key = f"{method}:{processor}"
            if key not in method_processors:
                method_processors[key] = {"volume": 0.0, "fees": 0.0}
            method_processors[key]["volume"] += amount
            method_processors[key]["fees"] += fee

        recommendations: list[dict[str, Any]] = []

        for analysis in fee_analyses:
            method = analysis.get("payment_method", "unknown")
            current_fee_pct = float(analysis.get("avg_fee_pct", 0.0))
            monthly_volume = float(analysis.get("total_volume", 0.0))

            # Find cheapest processor for this method
            best_processor = "current"
            best_fee_pct = current_fee_pct

            for fee_schedule in fees:
                processor = str(fee_schedule.get("processor", "unknown"))
                base_fee = float(fee_schedule.get("base_fee", 0.0))
                pct_fee = float(fee_schedule.get("pct_fee", 0.0))

                txn_count = int(analysis.get("transaction_count", 1))
                if txn_count > 0 and monthly_volume > 0:
                    total_est_fee = base_fee * txn_count + pct_fee / 100 * monthly_volume
                    est_pct = round(total_est_fee / monthly_volume * 100, 3)
                else:
                    est_pct = pct_fee

                if est_pct < best_fee_pct:
                    best_fee_pct = est_pct
                    best_processor = processor

            monthly_savings = round(
                monthly_volume * (current_fee_pct - best_fee_pct) / 100, 2,
            )

            recommendations.append({
                "payment_method": method,
                "recommended_processor": best_processor,
                "current_fee_pct": round(current_fee_pct, 3),
                "optimized_fee_pct": round(best_fee_pct, 3),
                "monthly_savings": max(monthly_savings, 0.0),
            })

        return {"status": "success", "recommendations": recommendations}
    except Exception as exc:
        return {"status": "error", "recommendations": [], "error": f"Routing optimization failed: {exc}"}
