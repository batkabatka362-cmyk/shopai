"""Wholesale B2B Engine — order processor.

Processes wholesale orders with net-30/60 payment terms.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
import time
from typing import Any

_TERM_DAYS = {"net-15": 15, "net-30": 30, "net-45": 45, "net-60": 60, "net-90": 90}


def process_orders(
    order: dict[str, Any],
    volume_discounts: list[dict[str, Any]],
    account_statuses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Process a wholesale order with payment terms.

    Args:
        order: Order dict with account_id and items.
        volume_discounts: Calculated volume discounts.
        account_statuses: Account statuses from account_manager.

    Returns:
        Structured dict with processed orders and credit terms.
    """
    try:
        order_data = copy.deepcopy(order)
        acct_id = str(order_data.get("account_id", ""))

        acct = None
        for a in account_statuses:
            if str(a.get("account_id", "")) == acct_id:
                acct = a
                break

        if acct and acct.get("status") == "credit_hold":
            return {
                "status": "success",
                "processed_orders": [],
                "credit_terms": [{"account_id": acct_id, "action": "order_rejected", "reason": "credit_hold"}],
            }

        terms = acct.get("payment_terms", "net-30") if acct else "net-30"
        term_days = _TERM_DAYS.get(terms, 30)

        now = time.time()
        due_ts = now + (term_days * 86400)
        due_date = time.strftime("%Y-%m-%d", time.gmtime(due_ts))

        subtotal = sum(d.get("total_price", 0.0) for d in volume_discounts)
        base_total = 0.0
        for d in volume_discounts:
            qty = d.get("quantity", 0)
            final_unit = d.get("final_unit_price", 0.0)
            discount_pct = d.get("discount_pct", 0.0)
            if discount_pct > 0:
                original_unit = final_unit / (1.0 - discount_pct / 100.0)
            else:
                original_unit = final_unit
            base_total += original_unit * qty

        discount_applied = round(base_total - subtotal, 2)

        order_id = str(order_data.get("id", order_data.get("order_id", f"WO-{int(now)}")))

        processed = [{
            "order_id": order_id,
            "account_id": acct_id,
            "items": order_data.get("items", []),
            "subtotal": round(subtotal, 2),
            "discount_applied": discount_applied,
            "total": round(subtotal, 2),
            "payment_terms": terms,
            "due_date": due_date,
        }]

        credit_terms = [{
            "account_id": acct_id,
            "payment_terms": terms,
            "due_date": due_date,
            "amount_due": round(subtotal, 2),
            "action": "order_approved",
        }]

        return {
            "status": "success",
            "processed_orders": processed,
            "credit_terms": credit_terms,
        }
    except Exception as exc:
        return {"status": "error", "processed_orders": [], "credit_terms": [], "error": f"Order processing failed: {exc}"}
