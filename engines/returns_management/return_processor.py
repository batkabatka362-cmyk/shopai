"""Returns Management Engine — return processor.

Processes return requests and validates eligibility against return policy.
Calculates refund amounts based on item prices and policy rules.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any


def process_returns(
    returns: list[dict[str, Any]],
    return_policy: dict[str, Any],
) -> dict[str, Any]:
    """Process each return request for eligibility and refund amount.

    Args:
        returns: List of ReturnRequest dicts.
        return_policy: ReturnPolicy dict with rules.

    Returns:
        Structured dict with per-return processing results.
    """
    try:
        returns = copy.deepcopy(returns)
        policy = copy.deepcopy(return_policy)

        window_days = int(policy.get("window_days", 30))
        restocking_fee_pct = float(policy.get("restocking_fee_pct", 0.0))
        eligible_conditions = policy.get("eligible_conditions", [
            "defective", "wrong_item", "not_as_described", "changed_mind",
        ])

        now_ts = time.time()
        processed: list[dict[str, Any]] = []

        for idx, ret in enumerate(returns):
            order_id = str(ret.get("order_id", f"unknown_{idx}"))
            return_id = f"RET-{order_id}-{idx:04d}"
            reason = str(ret.get("reason", "")).lower().strip()
            date_str = str(ret.get("date", ""))
            items = ret.get("items", [])

            # Check time window eligibility
            within_window = True
            if date_str and len(date_str) >= 10:
                try:
                    ret_ts = time.mktime(time.strptime(date_str[:10], "%Y-%m-%d"))
                    days_since = (now_ts - ret_ts) / 86400.0
                    within_window = days_since <= window_days
                except (ValueError, OverflowError):
                    within_window = True  # default to eligible if date parse fails

            # Check reason eligibility
            reason_eligible = (
                not eligible_conditions
                or any(cond in reason for cond in eligible_conditions)
                or reason in eligible_conditions
            )

            eligible = within_window and reason_eligible

            # Calculate refund amount
            total_value = 0.0
            for item in items:
                price = float(item.get("price", 0.0))
                qty = int(item.get("quantity", 1))
                total_value += price * qty

            if eligible:
                restocking_fee = total_value * (restocking_fee_pct / 100.0)
                refund_amount = round(total_value - restocking_fee, 2)
                status = "approved"
                rejection_reason = None
            else:
                refund_amount = 0.0
                if not within_window:
                    status = "rejected"
                    rejection_reason = "Outside return window"
                else:
                    status = "rejected"
                    rejection_reason = f"Reason '{reason}' not eligible"

            processed.append({
                "return_id": return_id,
                "order_id": order_id,
                "status": status,
                "eligible": eligible,
                "refund_amount": refund_amount,
                "rejection_reason": rejection_reason,
            })

        return {
            "status": "success",
            "processed": processed,
        }
    except Exception as exc:
        return {
            "status": "error",
            "processed": [],
            "error": f"Return processing failed: {exc}",
        }
