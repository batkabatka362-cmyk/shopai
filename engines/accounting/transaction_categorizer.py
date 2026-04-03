"""Accounting Engine — transaction categorizer.

Maps each transaction to the appropriate chart-of-accounts entries.
Auto-detects transaction type from description when not specified.

All categorization is deterministic — no AI calls.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------

CHART_OF_ACCOUNTS: dict[str, dict[str, str]] = {
    "1000": {"name": "Cash/Bank", "type": "asset"},
    "1100": {"name": "Accounts Receivable", "type": "asset"},
    "1200": {"name": "Inventory", "type": "asset"},
    "2000": {"name": "Accounts Payable", "type": "liability"},
    "2100": {"name": "Tax Payable", "type": "liability"},
    "3000": {"name": "Owner's Equity", "type": "equity"},
    "3100": {"name": "Retained Earnings", "type": "equity"},
    "4000": {"name": "Revenue / Sales", "type": "revenue"},
    "5000": {"name": "Cost of Goods Sold", "type": "expense"},
    "6000": {"name": "Operating Expenses", "type": "expense"},
    "6100": {"name": "Payment Processing Fees", "type": "expense"},
    "6200": {"name": "Shipping Expenses", "type": "expense"},
    "6300": {"name": "Marketing Expenses", "type": "expense"},
    "6400": {"name": "Software/Subscriptions", "type": "expense"},
    "6500": {"name": "General & Administrative", "type": "expense"},
}

# Keywords for auto-detecting transaction type from description
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "sale": ["order", "sale", "purchase", "sold", "payment received"],
    "refund": ["refund", "return", "reversal", "chargeback"],
    "expense": ["expense", "supply", "supplies", "office", "rent", "utility"],
    "fee": ["fee", "processing", "stripe", "paypal fee", "transaction fee"],
    "payout": ["payout", "transfer", "withdrawal", "bank transfer", "deposit"],
}

# Account mappings per transaction type
_TYPE_ACCOUNTS: dict[str, list[dict[str, str]]] = {
    "sale": [
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
        {"code": "4000", "name": "Revenue / Sales", "type": "revenue"},
        {"code": "5000", "name": "Cost of Goods Sold", "type": "expense"},
        {"code": "1200", "name": "Inventory", "type": "asset"},
        {"code": "2100", "name": "Tax Payable", "type": "liability"},
    ],
    "refund": [
        {"code": "4000", "name": "Revenue / Sales", "type": "revenue"},
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
        {"code": "1200", "name": "Inventory", "type": "asset"},
        {"code": "5000", "name": "Cost of Goods Sold", "type": "expense"},
    ],
    "expense": [
        {"code": "6000", "name": "Operating Expenses", "type": "expense"},
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
    ],
    "fee": [
        {"code": "6100", "name": "Payment Processing Fees", "type": "expense"},
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
    ],
    "payout": [
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
        {"code": "1000", "name": "Cash/Bank", "type": "asset"},
    ],
}

# Expense sub-type mapping based on description keywords
_EXPENSE_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "shipping": ("6200", "Shipping Expenses"),
    "freight": ("6200", "Shipping Expenses"),
    "postage": ("6200", "Shipping Expenses"),
    "marketing": ("6300", "Marketing Expenses"),
    "advertising": ("6300", "Marketing Expenses"),
    "ads": ("6300", "Marketing Expenses"),
    "software": ("6400", "Software/Subscriptions"),
    "subscription": ("6400", "Software/Subscriptions"),
    "saas": ("6400", "Software/Subscriptions"),
    "admin": ("6500", "General & Administrative"),
    "office": ("6500", "General & Administrative"),
    "rent": ("6500", "General & Administrative"),
}


def categorize_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    """Categorize a transaction into chart-of-accounts entries.

    Args:
        transaction: Single Transaction dict.

    Returns:
        Structured dict with category, accounts, and flags.
    """
    try:
        txn = copy.deepcopy(transaction)

        txn_type = str(txn.get("type", "")).strip().lower()
        description = str(txn.get("description", "")).strip().lower()

        # Auto-detect type from description if not provided
        if not txn_type:
            txn_type = _detect_type(description)

        if txn_type not in _TYPE_ACCOUNTS:
            return _fail(
                f"Unknown transaction type: '{txn_type}'. "
                f"Valid types: {list(_TYPE_ACCOUNTS.keys())}"
            )

        # Get accounts for this type
        accounts = copy.deepcopy(_TYPE_ACCOUNTS[txn_type])

        # Refine expense category based on description
        if txn_type == "expense":
            code, name = _detect_expense_category(description)
            accounts[0] = {"code": code, "name": name, "type": "expense"}

        category = _type_to_category(txn_type)
        is_revenue = txn_type == "sale"
        is_expense = txn_type in ("expense", "fee")

        return {
            "status": "success",
            "category": category,
            "transaction_type": txn_type,
            "accounts": accounts,
            "is_revenue": is_revenue,
            "is_expense": is_expense,
        }
    except Exception as exc:
        return _fail(f"Categorization failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_type(description: str) -> str:
    """Auto-detect transaction type from description keywords."""
    desc_lower = description.lower()
    for txn_type, keywords in _TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in desc_lower:
                return txn_type
    return "sale"  # default to sale if ambiguous


def _detect_expense_category(description: str) -> tuple[str, str]:
    """Map an expense description to a specific expense account."""
    desc_lower = description.lower()
    for keyword, (code, name) in _EXPENSE_CATEGORY_MAP.items():
        if keyword in desc_lower:
            return code, name
    return "6000", "Operating Expenses"


def _type_to_category(txn_type: str) -> str:
    """Map transaction type to a human-readable category name."""
    return {
        "sale": "Revenue",
        "refund": "Revenue Reversal",
        "expense": "Operating Expense",
        "fee": "Payment Processing Fee",
        "payout": "Bank Transfer",
    }.get(txn_type, "Uncategorized")


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "category": None,
        "transaction_type": None,
        "accounts": [],
        "is_revenue": False,
        "is_expense": False,
        "error": reason,
    }
