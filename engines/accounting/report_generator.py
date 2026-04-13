"""Accounting Engine — report generator.

Generates financial reports: Profit & Loss, Balance Sheet, General Ledger.
All calculations are real — revenue, COGS, margins, equation checks.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Account code ranges for classification
# ---------------------------------------------------------------------------

_REVENUE_CODES = {"4000"}
_COGS_CODES = {"5000"}
_EXPENSE_CODES = {"6000", "6100", "6200", "6300", "6400", "6500"}
_ASSET_CODES = {"1000", "1100", "1200"}
_LIABILITY_CODES = {"2000", "2100"}
_EQUITY_CODES = {"3000", "3100"}


def generate_report(
    balances: dict[str, Any],
    transactions: list[dict[str, Any]],
    report_type: str,
    period: dict[str, str],
) -> dict[str, Any]:
    """Generate a financial report.

    Args:
        balances: Balance result from balance_calculator (with "balances" key).
        transactions: Original transaction list (for ledger report).
        report_type: One of "profit_and_loss", "balance_sheet", "ledger".
        period: Dict with "start" and "end" date strings.

    Returns:
        Structured dict with the report.
    """
    try:
        bal = copy.deepcopy(balances)
        account_balances = bal.get("balances", {})

        if report_type == "profit_and_loss":
            return _profit_and_loss(account_balances, period)
        elif report_type == "balance_sheet":
            return _balance_sheet(account_balances, bal, period)
        elif report_type == "ledger":
            return _general_ledger(transactions, period)
        else:
            return _fail(
                f"Unknown report type: '{report_type}'. "
                f"Valid types: profit_and_loss, balance_sheet, ledger"
            )
    except Exception as exc:
        return _fail(f"Report generation failed: {exc}")


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def _profit_and_loss(
    balances: dict[str, float],
    period: dict[str, str],
) -> dict[str, Any]:
    """Build a Profit & Loss (Income Statement).

    Structure:
      Revenue
      - COGS
      = Gross Profit
      - Operating Expenses (broken out by category)
      = Net Profit
    """
    # Revenue
    total_revenue = sum(
        balances.get(code, 0.0) for code in _REVENUE_CODES
    )

    # COGS
    total_cogs = sum(
        balances.get(code, 0.0) for code in _COGS_CODES
    )

    # Gross profit
    gross_profit = round(total_revenue - total_cogs, 2)

    # Operating expenses (detailed breakdown)
    expense_breakdown: dict[str, float] = {}
    total_operating_expenses = 0.0
    for code in sorted(_EXPENSE_CODES):
        bal = balances.get(code, 0.0)
        if bal != 0.0:
            expense_breakdown[code] = round(bal, 2)
            total_operating_expenses += bal
    total_operating_expenses = round(total_operating_expenses, 2)

    # Net profit
    net_profit = round(gross_profit - total_operating_expenses, 2)

    # Margins
    gross_margin_pct = (
        round((gross_profit / total_revenue) * 100, 2)
        if total_revenue > 0 else 0.0
    )
    net_margin_pct = (
        round((net_profit / total_revenue) * 100, 2)
        if total_revenue > 0 else 0.0
    )

    return {
        "status": "success",
        "report": {
            "type": "profit_and_loss",
            "period": period,
            "revenue": round(total_revenue, 2),
            "cogs": round(total_cogs, 2),
            "gross_profit": gross_profit,
            "operating_expenses": total_operating_expenses,
            "expense_breakdown": expense_breakdown,
            "net_profit": net_profit,
            "gross_margin_pct": gross_margin_pct,
            "net_margin_pct": net_margin_pct,
        },
    }


def _balance_sheet(
    balances: dict[str, float],
    full_balance_result: dict[str, Any],
    period: dict[str, str],
) -> dict[str, Any]:
    """Build a Balance Sheet.

    Structure:
      Assets
        Current Assets (Cash, AR, Inventory)
      = Total Assets

      Liabilities
        Current Liabilities (AP, Tax Payable)
      + Equity
        Owner's Equity + Retained Earnings + Net Income
      = Total Liabilities + Equity
    """
    # Assets
    asset_detail: dict[str, float] = {}
    total_assets = 0.0
    for code in sorted(_ASSET_CODES):
        bal = balances.get(code, 0.0)
        asset_detail[code] = round(bal, 2)
        total_assets += bal
    total_assets = round(total_assets, 2)

    # Liabilities
    liability_detail: dict[str, float] = {}
    total_liabilities = 0.0
    for code in sorted(_LIABILITY_CODES):
        bal = balances.get(code, 0.0)
        liability_detail[code] = round(bal, 2)
        total_liabilities += bal
    total_liabilities = round(total_liabilities, 2)

    # Equity
    equity_detail: dict[str, float] = {}
    total_equity = 0.0
    for code in sorted(_EQUITY_CODES):
        bal = balances.get(code, 0.0)
        equity_detail[code] = round(bal, 2)
        total_equity += bal

    # Net income from P&L flows into retained earnings
    equation_data = full_balance_result.get("equation", {})
    net_income = round(
        equation_data.get("revenue", 0.0) - equation_data.get("expenses", 0.0), 2
    )
    equity_detail["net_income"] = net_income
    total_equity = round(total_equity + net_income, 2)

    total_liabilities_equity = round(total_liabilities + total_equity, 2)
    is_balanced = total_assets == total_liabilities_equity

    return {
        "status": "success",
        "report": {
            "type": "balance_sheet",
            "period": period,
            "assets": asset_detail,
            "total_assets": total_assets,
            "liabilities": liability_detail,
            "total_liabilities": total_liabilities,
            "equity": equity_detail,
            "total_equity": total_equity,
            "total_liabilities_and_equity": total_liabilities_equity,
            "is_balanced": is_balanced,
        },
    }


def _general_ledger(
    transactions: list[dict[str, Any]],
    period: dict[str, str],
) -> dict[str, Any]:
    """Build a General Ledger report — all transactions for the period.

    Filters transactions by date within the period range.
    """
    start = period.get("start", "")
    end = period.get("end", "")

    filtered: list[dict[str, Any]] = []
    for txn in transactions:
        txn_date = str(txn.get("date", ""))
        if start <= txn_date <= end:
            filtered.append(copy.deepcopy(txn))

    return {
        "status": "success",
        "report": {
            "type": "ledger",
            "period": period,
            "entries": filtered,
            "entry_count": len(filtered),
        },
    }


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized error dict."""
    return {
        "status": "error",
        "report": {},
        "error": reason,
    }
