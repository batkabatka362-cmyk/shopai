"""Payment Optimization Engine — fraud cost tracker.

Tracks fraud-related costs: losses, chargebacks, and prevention costs.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def track_fraud_costs(
    transactions: list[dict[str, Any]],
    fees: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track fraud-related costs.

    Args:
        transactions: List of transaction dicts.
        fees: Fee schedules (for chargeback fees).

    Returns:
        Structured dict with fraud cost tracking results.
    """
    try:
        fraud_losses = 0.0
        chargeback_count = 0

        for txn in transactions:
            is_fraud = txn.get("is_fraud", False)
            amount = float(txn.get("amount", 0.0))
            status = str(txn.get("status", ""))

            if is_fraud:
                fraud_losses += amount
            if status == "chargeback":
                chargeback_count += 1

        # Average chargeback fee across processors
        chargeback_fees_per = []
        for fee_schedule in fees:
            cb_fee = float(fee_schedule.get("chargeback_fee", 15.0))
            chargeback_fees_per.append(cb_fee)

        avg_cb_fee = (
            sum(chargeback_fees_per) / len(chargeback_fees_per)
            if chargeback_fees_per else 15.0
        )
        total_chargeback_fees = round(chargeback_count * avg_cb_fee, 2)

        # Estimate prevention cost as 0.5% of total volume
        total_volume = sum(float(t.get("amount", 0.0)) for t in transactions)
        prevention_cost = round(total_volume * 0.005, 2)

        net_fraud_cost = round(
            fraud_losses + total_chargeback_fees + prevention_cost, 2,
        )

        result = {
            "fraud_losses": round(fraud_losses, 2),
            "chargeback_count": chargeback_count,
            "chargeback_fees": total_chargeback_fees,
            "prevention_cost": prevention_cost,
            "net_fraud_cost": net_fraud_cost,
        }

        return {"status": "success", "fraud_costs": result}
    except Exception as exc:
        return {"status": "error", "fraud_costs": {}, "error": f"Fraud cost tracking failed: {exc}"}
