"""Accounting Engine — balance calculator.

Processes journal entries to compute running account balances.
Validates the accounting equation: Assets = Liabilities + Equity.

All math is real. No faking.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Account type classification (for balance direction and equation check)
# ---------------------------------------------------------------------------

_ACCOUNT_TYPES: dict[str, str] = {
    "1000": "asset",
    "1100": "asset",
    "1200": "asset",
    "2000": "liability",
    "2100": "liability",
    "3000": "equity",
    "3100": "equity",
    "4000": "revenue",
    "5000": "expense",
    "6000": "expense",
    "6100": "expense",
    "6200": "expense",
    "6300": "expense",
    "6400": "expense",
    "6500": "expense",
}


def calculate_balances(
    journal_entries: list[dict[str, Any]],
    existing_balances: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Calculate account balances from journal entries.

    Applies normal balance rules:
      - Assets & Expenses: debit increases, credit decreases
      - Liabilities, Equity & Revenue: credit increases, debit decreases

    Args:
        journal_entries: List of JournalEntry dicts.
        existing_balances: Optional starting balances per account code.

    Returns:
        Structured dict with balances, totals, and balance check.
    """
    try:
        entries = copy.deepcopy(journal_entries)
        balances: dict[str, float] = {}

        if existing_balances:
            balances = copy.deepcopy(existing_balances)

        total_debits = 0.0
        total_credits = 0.0

        for entry in entries:
            lines = entry.get("lines", [])
            for line in lines:
                account = str(line.get("account", ""))
                line_type = str(line.get("type", ""))
                amount = float(line.get("amount", 0.0))

                if account not in balances:
                    balances[account] = 0.0

                acct_type = _ACCOUNT_TYPES.get(account, "asset")

                # Normal balance rules
                if line_type == "debit":
                    total_debits += amount
                    if acct_type in ("asset", "expense"):
                        balances[account] += amount  # increases
                    else:
                        balances[account] -= amount  # decreases
                elif line_type == "credit":
                    total_credits += amount
                    if acct_type in ("asset", "expense"):
                        balances[account] -= amount  # decreases
                    else:
                        balances[account] += amount  # increases

        # Round all balances
        balances = {k: round(v, 2) for k, v in balances.items()}
        total_debits = round(total_debits, 2)
        total_credits = round(total_credits, 2)

        # Validate accounting equation: Assets = Liabilities + Equity
        # Revenue increases equity (retained earnings), expenses decrease it
        total_assets = sum(
            balances.get(code, 0.0)
            for code, atype in _ACCOUNT_TYPES.items()
            if atype == "asset"
        )
        total_liabilities = sum(
            balances.get(code, 0.0)
            for code, atype in _ACCOUNT_TYPES.items()
            if atype == "liability"
        )
        total_equity = sum(
            balances.get(code, 0.0)
            for code, atype in _ACCOUNT_TYPES.items()
            if atype == "equity"
        )
        total_revenue = sum(
            balances.get(code, 0.0)
            for code, atype in _ACCOUNT_TYPES.items()
            if atype == "revenue"
        )
        total_expenses = sum(
            balances.get(code, 0.0)
            for code, atype in _ACCOUNT_TYPES.items()
            if atype == "expense"
        )

        # Assets = Liabilities + Equity + Revenue - Expenses
        # (Revenue and Expenses are temporary equity accounts)
        lhs = round(total_assets, 2)
        rhs = round(total_liabilities + total_equity + total_revenue - total_expenses, 2)
        is_balanced = lhs == rhs

        return {
            "status": "success",
            "balances": balances,
            "total_debits": total_debits,
            "total_credits": total_credits,
            "is_balanced": is_balanced,
            "equation": {
                "assets": round(total_assets, 2),
                "liabilities": round(total_liabilities, 2),
                "equity": round(total_equity, 2),
                "revenue": round(total_revenue, 2),
                "expenses": round(total_expenses, 2),
            },
        }
    except Exception as exc:
        return _fail(f"Balance calculation failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "balances": {},
        "total_debits": 0.0,
        "total_credits": 0.0,
        "is_balanced": False,
        "error": reason,
    }
