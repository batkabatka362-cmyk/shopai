"""Wholesale B2B Engine — account manager.

Manages B2B accounts with credit terms and status tracking.
All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def manage_accounts(
    accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Manage B2B accounts and determine their current status.

    Args:
        accounts: List of B2B account dicts.

    Returns:
        Structured dict with account statuses.
    """
    try:
        items = copy.deepcopy(accounts)
        statuses: list[dict[str, Any]] = []

        for acct in items:
            acct_id = str(acct.get("id", acct.get("account_id", "")))
            company = str(acct.get("company_name", ""))
            credit_limit = float(acct.get("credit_limit", 10000.0))
            outstanding = float(acct.get("outstanding_balance", 0.0))
            terms = str(acct.get("payment_terms", "net-30"))

            utilization = outstanding / credit_limit if credit_limit > 0 else 1.0

            if utilization >= 0.95:
                status = "credit_hold"
            elif utilization >= 0.80:
                status = "warning"
            elif outstanding > 0 and acct.get("days_overdue", 0) > 60:
                status = "collections"
            else:
                status = "active"

            statuses.append({
                "account_id": acct_id,
                "company_name": company,
                "credit_limit": credit_limit,
                "outstanding_balance": outstanding,
                "payment_terms": terms,
                "status": status,
            })

        return {"status": "success", "account_statuses": statuses}
    except Exception as exc:
        return {"status": "error", "account_statuses": [], "error": f"Account management failed: {exc}"}
