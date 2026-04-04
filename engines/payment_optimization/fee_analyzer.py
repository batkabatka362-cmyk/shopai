"""Payment Optimization Engine — fee analyzer.

Analyzes payment processing fees by method, computing totals,
averages, and volume breakdowns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_fees(
    transactions: list[dict[str, Any]],
    payment_methods: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze fees by payment method.

    Args:
        transactions: List of transaction dicts.
        payment_methods: List of payment method dicts.

    Returns:
        Structured dict with per-method fee analyses.
    """
    try:
        method_stats: dict[str, dict[str, float]] = {}

        for txn in transactions:
            method = str(txn.get("payment_method", "unknown"))
            amount = float(txn.get("amount", 0.0))
            fee = float(txn.get("fee", 0.0))

            if method not in method_stats:
                method_stats[method] = {
                    "total_fees": 0.0,
                    "total_volume": 0.0,
                    "count": 0,
                }

            method_stats[method]["total_fees"] += fee
            method_stats[method]["total_volume"] += amount
            method_stats[method]["count"] += 1

        analyses: list[dict[str, Any]] = []
        for method, stats in method_stats.items():
            total_volume = stats["total_volume"]
            total_fees = stats["total_fees"]
            avg_fee_pct = round(
                (total_fees / total_volume * 100) if total_volume > 0 else 0.0, 3,
            )

            analyses.append({
                "payment_method": method,
                "total_fees": round(total_fees, 2),
                "avg_fee_pct": avg_fee_pct,
                "transaction_count": int(stats["count"]),
                "total_volume": round(total_volume, 2),
            })

        analyses.sort(key=lambda a: a["total_fees"], reverse=True)

        return {"status": "success", "analyses": analyses}
    except Exception as exc:
        return {"status": "error", "analyses": [], "error": f"Fee analysis failed: {exc}"}
