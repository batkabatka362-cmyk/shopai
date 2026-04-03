"""Accounting Engine — all TypedDicts and type aliases.

Single source of truth for every data shape in the accounting engine.
No logic here — only type definitions.
"""
from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

class Transaction(TypedDict, total=False):
    """Single financial transaction."""
    id: str
    date: str
    type: str
    description: str
    amount: float
    currency: str
    source: str
    fees: float
    tax_amount: float
    cogs: float


class AccountingInputData(TypedDict, total=False):
    """The 'data' block of engine input."""
    transactions: list[Transaction]
    report_type: str
    period: dict[str, str]
    bank_transactions: list[dict[str, Any]]


class AccountingInput(TypedDict, total=False):
    """Full engine input payload."""
    status: str
    data: AccountingInputData
    meta: dict[str, Any]
    error: str | None


# ---------------------------------------------------------------------------
# Intermediate types — journal entries
# ---------------------------------------------------------------------------

class JournalLine(TypedDict):
    """Single line in a journal entry (one debit or credit)."""
    account: str
    account_name: str
    type: str  # "debit" or "credit"
    amount: float


class JournalEntry(TypedDict):
    """A complete journal entry with balanced debit/credit lines."""
    id: str
    date: str
    description: str
    lines: list[JournalLine]


# ---------------------------------------------------------------------------
# Intermediate types — account balance
# ---------------------------------------------------------------------------

class AccountBalance(TypedDict):
    """Balance state for all accounts."""
    balances: dict[str, float]
    total_debits: float
    total_credits: float
    is_balanced: bool


# ---------------------------------------------------------------------------
# Intermediate types — reconciliation
# ---------------------------------------------------------------------------

class Discrepancy(TypedDict, total=False):
    """Single reconciliation discrepancy."""
    internal: dict[str, Any]
    bank: dict[str, Any]
    difference: float


class ReconciliationResult(TypedDict):
    """Result from bank reconciliation."""
    matched_count: int
    unmatched_internal: int
    unmatched_bank: int
    discrepancies: list[Discrepancy]
    status: str


# ---------------------------------------------------------------------------
# Intermediate types — financial report
# ---------------------------------------------------------------------------

class FinancialReport(TypedDict, total=False):
    """Generated financial report."""
    type: str
    period: dict[str, str]
    revenue: float
    cogs: float
    gross_profit: float
    operating_expenses: float
    net_profit: float
    gross_margin_pct: float
    net_margin_pct: float
    assets: float
    liabilities: float
    equity: float
    entries: list[JournalEntry]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class AccountingOutputData(TypedDict, total=False):
    """The 'data' block of the engine output."""
    journal_entries: list[JournalEntry]
    balances: AccountBalance
    reconciliation: ReconciliationResult | None
    report: FinancialReport


class AccountingMeta(TypedDict):
    """The 'meta' block of the engine output."""
    engine: str
    timestamp: str
    elapsed_seconds: float


class AccountingOutput(TypedDict):
    """Final output of the accounting engine."""
    status: str
    data: AccountingOutputData | None
    meta: AccountingMeta
    error: str | None
