"""Accounting Engine — transaction categorizer.

Maps each transaction to the correct chart-of-accounts categories
based on transaction type. Auto-detects type from description if missing.

All categorization is deterministic. No AI calls.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------

CHART_OF_ACCOUNTS = {
    1000: {"name": "Cash/Bank", "type": "asset", "normal_side": "debit"},
    1100: {"name": "Accounts Receivable", "type": "asset", "normal_side": "debit"},
    1200: {"name": "Inventory", "type": "asset", "normal_side": "debit"},
    2000: {"name": "Accounts Payable", "type": "liability", "normal_side": "credit"},
    2100: {"name": "Tax Payable", "type": "liability", "normal_side": "credit"},
    3000: {"name": "Owner's Equity", "type": "equity", "normal_side": "credit"},
    3100: {"name": "Retained Earnings", "type": "equity", "normal_side": "credit"},
    4000: {"name": "Revenue / Sales", "type": "revenue", "normal_side": "credit"},
    5000: {"name": "Cost of Goods Sold", "type": "expense", "normal_side": "debit"},
    6000: {"name": "Operating Expenses", "type": "expense", "normal_side": "debit"},
    6100: {"name": "Payment Processing Fees", "type": "expense", "normal_side": "debit"},
    6200: {"name": "Shipping Expenses", "type": "expense", "normal_side": "debit"},
    6300: {"name": "Marketing Expenses", "type": "expense", "normal_side": "debit"},
    6400: {"name": "Software/Subscriptions", "type": "expense", "normal_side": "debit"},
    6500: {"name": "General & Administrative", "type": "expense", "normal_side": "debit"},
}

# ---------------------------------------------------------------------------
# Type detection keywords
# ---------------------------------------------------------------------------

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "sale": ["order", "sale", "purchase", "sold", "payment received"],
    "refund": ["refund", "return", "reversal", "chargeback"],
    "expense": ["expense", "supplies", "rent", "utilities", "payroll"],
    "fee": ["fee", "processing", "stripe", "paypal fee", "transaction fee"],
    "payout": ["payout", "transfer", "withdrawal", "bank transfer"],
    "shipping": ["shipping", "postage", "freight", "delivery"],
    "marketing": ["marketing", "ads", "advertising", "campaign", "promotion"],
    "software": ["software", "subscription", "saas", "hosting", "app"],
}

# ---------------------------------------------------------------------------
# Category mappings per transaction type
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, dict[str, Any]] = {
    "sale": {
        "category": "Revenue",
        "accounts": [
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
            {"code": 4000, "name": "Revenue / Sales", "type": "revenue"},
            {"code": 5000, "name": "Cost of Goods Sold", "type": "expense"},
            {"code": 1200, "name": "Inventory", "type": "asset"},
        ],
        "is_revenue": True,
        "is_expense": False,
    },
    "refund": {
        "category": "Revenue Reversal",
        "accounts": [
            {"code": 4000, "name": "Revenue / Sales", "type": "revenue"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": False,
    },
    "expense": {
        "category": "Operating Expense",
        "accounts": [
            {"code": 6000, "name": "Operating Expenses", "type": "expense"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": True,
    },
    "fee": {
        "category": "Payment Processing Fee",
        "accounts": [
            {"code": 6100, "name": "Payment Processing Fees", "type": "expense"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": True,
    },
    "payout": {
        "category": "Bank Transfer",
        "accounts": [
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": False,
    },
    "shipping": {
        "category": "Shipping Expense",
        "accounts": [
            {"code": 6200, "name": "Shipping Expenses", "type": "expense"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": True,
    },
    "marketing": {
        "category": "Marketing Expense",
        "accounts": [
            {"code": 6300, "name": "Marketing Expenses", "type": "expense"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": True,
    },
    "software": {
        "category": "Software/Subscription",
        "accounts": [
            {"code": 6400, "name": "Software/Subscriptions", "type": "expense"},
            {"code": 1000, "name": "Cash/Bank", "type": "asset"},
        ],
        "is_revenue": False,
        "is_expense": True,
    },
}


def categorize_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    """Categorize a transaction against the chart of accounts.

    Args:
        transaction: Single transaction dict with at least 'amount'.

    Returns:
        Structured dict with category, affected accounts, and flags.
    """
    try:
        txn = copy.deepcopy(transaction)

        txn_type = str(txn.get("type", "")).strip().lower()
        description = str(txn.get("description", "")).strip().lower()

        # Auto-detect type from description if not specified or unknown
        if txn_type not in _CATEGORY_MAP:
            txn_type = _detect_type(description)

        mapping = _CATEGORY_MAP.get(txn_type)
        if mapping is None:
            # Default to generic operating expense
            mapping = _CATEGORY_MAP["expense"]

        # Add tax-related accounts for sales with tax
        accounts = copy.deepcopy(mapping["accounts"])
        tax_amount = float(txn.get("tax_amount", 0.0))
        if txn_type == "sale" and tax_amount > 0:
            accounts.append({"code": 2100, "name": "Tax Payable", "type": "liability"})

        return {
            "status": "success",
            "transaction_id": str(txn.get("id", "")),
            "detected_type": txn_type,
            "category": mapping["category"],
            "accounts": accounts,
            "is_revenue": mapping["is_revenue"],
            "is_expense": mapping["is_expense"],
        }
    except Exception as exc:
        return {
            "status": "error",
            "category": "",
            "accounts": [],
            "is_revenue": False,
            "is_expense": False,
            "error": f"Transaction categorization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_type(description: str) -> str:
    """Detect transaction type from description keywords."""
    desc_lower = description.lower()
    for txn_type, keywords in _TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return txn_type
    return "expense"  # conservative default
