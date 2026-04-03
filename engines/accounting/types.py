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
    """Single transaction record."""
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
    account_code: int
    type: str  # "debit" or "credit"
    amount: float


class JournalEntry(TypedDict):
    """A complete journal entry with balanced debit/credit lines."""
    id: str
    date: str
    description: str
    lines: list[JournalLine]


# ---------------------------------------------------------------------------
# Intermediate types — account balances
# ---------------------------------------------------------------------------

class AccountBalance(TypedDict):
    """Balance state for a single account."""
    account_code: int
    account_name: str
    balance: float
    normal_side: str  # "debit" or "credit"


# ---------------------------------------------------------------------------
# Intermediate types — reconciliation
# ---------------------------------------------------------------------------

class ReconciliationDiscrepancy(TypedDict):
    """A mismatch between internal and bank records."""
    internal: dict[str, Any]
    bank: dict[str, Any]
    difference: float


class ReconciliationResult(TypedDict):
    """Result of bank reconciliation."""
    matched_count: int
    unmatched_internal: int
    unmatched_bank: int
    discrepancies: list[ReconciliationDiscrepancy]
    status: str


# ---------------------------------------------------------------------------
# Intermediate types — financial reports
# ---------------------------------------------------------------------------

class ProfitAndLossReport(TypedDict, total=False):
    """Profit and Loss report data."""
    type: str
    period: dict[str, str]
    revenue: float
    cost_of_goods_sold: float
    gross_profit: float
    gross_margin_pct: float
    operating_expenses: float
    net_profit: float
    net_margin_pct: float
    expense_breakdown: dict[str, float]


class BalanceSheetReport(TypedDict, total=False):
    """Balance Sheet report data."""
    type: str
    period: dict[str, str]
    total_assets: float
    total_liabilities: float
    total_equity: float
    is_balanced: bool
    assets: dict[str, float]
    liabilities: dict[str, float]
    equity: dict[str, float]


class FinancialReport(TypedDict, total=False):
    """Generic financial report wrapper."""
    type: str
    period: dict[str, str]


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------

class AccountingOutputData(TypedDict, total=False):
    """The 'data' block of engine output."""
    journal_entries: list[JournalEntry]
    balances: dict[str, float]
    reconciliation: ReconciliationResult | None
    report: dict[str, Any]
    transaction_count: int
    is_balanced: bool


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
