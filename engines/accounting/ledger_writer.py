"""Accounting Engine — ledger writer.

Creates double-entry journal entries from categorized transactions.
Every debit has a matching credit. Total debits must equal total credits.

All math is real double-entry bookkeeping.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


def write_journal_entries(
    transaction: dict[str, Any],
    category: dict[str, Any],
) -> dict[str, Any]:
    """Create double-entry journal entries for a categorized transaction.

    Args:
        transaction: The original Transaction dict.
        category: The categorization result from transaction_categorizer.

    Returns:
        Structured dict with journal entries and balance verification.
    """
    try:
        txn = copy.deepcopy(transaction)
        cat = copy.deepcopy(category)

        txn_type = cat.get("transaction_type", "")
        amount = float(txn.get("amount", 0.0))
        date = str(txn.get("date", ""))
        description = str(txn.get("description", ""))
        txn_id = str(txn.get("id", uuid.uuid4().hex[:8]))
        fees = float(txn.get("fees", 0.0))
        tax_amount = float(txn.get("tax_amount", 0.0))
        cogs = float(txn.get("cogs", 0.0))

        if amount <= 0 and txn_type != "refund":
            return _fail("Transaction amount must be positive")

        entries: list[dict[str, Any]] = []

        if txn_type == "sale":
            entries.append(_build_sale_entry(
                txn_id, date, description, amount, fees, tax_amount, cogs,
            ))
        elif txn_type == "refund":
            entries.append(_build_refund_entry(
                txn_id, date, description, amount, tax_amount, cogs,
            ))
        elif txn_type == "expense":
            expense_code = "6000"
            expense_name = "Operating Expenses"
            accounts = cat.get("accounts", [])
            if accounts:
                expense_code = accounts[0].get("code", "6000")
                expense_name = accounts[0].get("name", "Operating Expenses")
            entries.append(_build_expense_entry(
                txn_id, date, description, amount, expense_code, expense_name,
            ))
        elif txn_type == "fee":
            entries.append(_build_fee_entry(
                txn_id, date, description, fees if fees > 0 else amount,
            ))
        elif txn_type == "payout":
            entries.append(_build_payout_entry(
                txn_id, date, description, amount,
            ))
        else:
            return _fail(f"Unsupported transaction type for journal: {txn_type}")

        # If sale has fees, add a separate fee entry
        if txn_type == "sale" and fees > 0:
            entries.append(_build_fee_entry(
                f"{txn_id}_fee", date, f"{description} - Processing Fee", fees,
            ))

        # Validate all entries are balanced
        all_balanced = True
        for entry in entries:
            total_debits = sum(
                ln["amount"] for ln in entry["lines"] if ln["type"] == "debit"
            )
            total_credits = sum(
                ln["amount"] for ln in entry["lines"] if ln["type"] == "credit"
            )
            if round(total_debits, 2) != round(total_credits, 2):
                all_balanced = False

        return {
            "status": "success",
            "entries": entries,
            "balanced": all_balanced,
        }
    except Exception as exc:
        return _fail(f"Journal entry creation failed: {exc}")


# ---------------------------------------------------------------------------
# Entry builders
# ---------------------------------------------------------------------------

def _build_sale_entry(
    txn_id: str,
    date: str,
    description: str,
    amount: float,
    fees: float,
    tax_amount: float,
    cogs: float,
) -> dict[str, Any]:
    """Build journal entry for a sale transaction.

    Sale accounting:
      Debit  Cash/Bank (1000)        = amount (total received incl tax)
      Credit Revenue (4000)          = amount - tax_amount
      Credit Tax Payable (2100)      = tax_amount
      Debit  COGS (5000)             = cogs
      Credit Inventory (1200)        = cogs
    """
    lines: list[dict[str, Any]] = []

    # Cash received (full amount including tax)
    lines.append({
        "account": "1000",
        "account_name": "Cash/Bank",
        "type": "debit",
        "amount": round(amount, 2),
    })

    # Revenue (net of tax)
    revenue_amount = amount - tax_amount
    lines.append({
        "account": "4000",
        "account_name": "Revenue / Sales",
        "type": "credit",
        "amount": round(revenue_amount, 2),
    })

    # Tax payable
    if tax_amount > 0:
        lines.append({
            "account": "2100",
            "account_name": "Tax Payable",
            "type": "credit",
            "amount": round(tax_amount, 2),
        })

    # COGS and inventory reduction
    if cogs > 0:
        lines.append({
            "account": "5000",
            "account_name": "Cost of Goods Sold",
            "type": "debit",
            "amount": round(cogs, 2),
        })
        lines.append({
            "account": "1200",
            "account_name": "Inventory",
            "type": "credit",
            "amount": round(cogs, 2),
        })

    return {
        "id": f"je_{txn_id}",
        "date": date,
        "description": description,
        "lines": lines,
    }


def _build_refund_entry(
    txn_id: str,
    date: str,
    description: str,
    amount: float,
    tax_amount: float,
    cogs: float,
) -> dict[str, Any]:
    """Build journal entry for a refund (reversal of sale).

    Refund accounting (reverses the sale):
      Debit  Revenue (4000)         = amount - tax_amount
      Debit  Tax Payable (2100)     = tax_amount
      Credit Cash/Bank (1000)       = amount
      Debit  Inventory (1200)       = cogs
      Credit COGS (5000)            = cogs
    """
    lines: list[dict[str, Any]] = []

    revenue_amount = amount - tax_amount

    # Reverse revenue
    lines.append({
        "account": "4000",
        "account_name": "Revenue / Sales",
        "type": "debit",
        "amount": round(revenue_amount, 2),
    })

    # Reverse tax payable
    if tax_amount > 0:
        lines.append({
            "account": "2100",
            "account_name": "Tax Payable",
            "type": "debit",
            "amount": round(tax_amount, 2),
        })

    # Cash out
    lines.append({
        "account": "1000",
        "account_name": "Cash/Bank",
        "type": "credit",
        "amount": round(amount, 2),
    })

    # Reverse COGS / restore inventory
    if cogs > 0:
        lines.append({
            "account": "1200",
            "account_name": "Inventory",
            "type": "debit",
            "amount": round(cogs, 2),
        })
        lines.append({
            "account": "5000",
            "account_name": "Cost of Goods Sold",
            "type": "credit",
            "amount": round(cogs, 2),
        })

    return {
        "id": f"je_{txn_id}",
        "date": date,
        "description": f"Refund: {description}",
        "lines": lines,
    }


def _build_expense_entry(
    txn_id: str,
    date: str,
    description: str,
    amount: float,
    expense_code: str,
    expense_name: str,
) -> dict[str, Any]:
    """Build journal entry for an expense.

    Expense accounting:
      Debit  Expense account (6xxx)  = amount
      Credit Cash/Bank (1000)        = amount
    """
    return {
        "id": f"je_{txn_id}",
        "date": date,
        "description": description,
        "lines": [
            {
                "account": expense_code,
                "account_name": expense_name,
                "type": "debit",
                "amount": round(amount, 2),
            },
            {
                "account": "1000",
                "account_name": "Cash/Bank",
                "type": "credit",
                "amount": round(amount, 2),
            },
        ],
    }


def _build_fee_entry(
    txn_id: str,
    date: str,
    description: str,
    amount: float,
) -> dict[str, Any]:
    """Build journal entry for a processing fee.

    Fee accounting:
      Debit  Payment Processing Fees (6100) = amount
      Credit Cash/Bank (1000)                = amount
    """
    return {
        "id": f"je_{txn_id}",
        "date": date,
        "description": description,
        "lines": [
            {
                "account": "6100",
                "account_name": "Payment Processing Fees",
                "type": "debit",
                "amount": round(amount, 2),
            },
            {
                "account": "1000",
                "account_name": "Cash/Bank",
                "type": "credit",
                "amount": round(amount, 2),
            },
        ],
    }


def _build_payout_entry(
    txn_id: str,
    date: str,
    description: str,
    amount: float,
) -> dict[str, Any]:
    """Build journal entry for a payout (bank transfer, no P&L impact).

    Payout accounting (internal transfer):
      Debit  Cash/Bank - External (1000)  = amount
      Credit Cash/Bank - Platform (1000)  = amount

    Note: This is a transfer between cash sub-accounts.
    No revenue or expense impact.
    """
    return {
        "id": f"je_{txn_id}",
        "date": date,
        "description": f"Payout: {description}",
        "lines": [
            {
                "account": "1000",
                "account_name": "Cash/Bank (External)",
                "type": "debit",
                "amount": round(amount, 2),
            },
            {
                "account": "1000",
                "account_name": "Cash/Bank (Platform)",
                "type": "credit",
                "amount": round(amount, 2),
            },
        ],
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "entries": [],
        "balanced": False,
        "error": reason,
    }
