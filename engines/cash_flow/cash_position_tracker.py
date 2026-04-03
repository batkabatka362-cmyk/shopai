"""Cash Flow Engine — cash position tracker.

Tracks real-time cash position by summing period inflows and outflows,
computing net change, and projecting end-of-period balance.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


def track_cash_position(
    current_balance: float,
    inflows: list[dict[str, Any]],
    outflows: list[dict[str, Any]],
    period: dict[str, str],
) -> dict[str, Any]:
    """Track cash position for a given period.

    Filters inflows/outflows within the period window, sums them,
    and computes the projected end balance.

    Args:
        current_balance: Current cash balance.
        inflows: List of CashInflow dicts.
        outflows: List of CashOutflow dicts.
        period: Dict with 'start' and 'end' date strings (YYYY-MM-DD).

    Returns:
        Structured dict with cash position details.
    """
    try:
        inflows = copy.deepcopy(inflows)
        outflows = copy.deepcopy(outflows)

        period_start = _parse_date(period.get("start", ""))
        period_end = _parse_date(period.get("end", ""))

        # Sum inflows within the period
        period_inflows = 0.0
        for item in inflows:
            amount = float(item.get("amount", 0.0))
            if amount <= 0:
                continue
            item_date = _parse_date(item.get("date", ""))
            if item_date is None:
                # No date — include by default
                period_inflows += amount
            elif _in_period(item_date, period_start, period_end):
                period_inflows += amount

        # Sum outflows within the period
        period_outflows = 0.0
        for item in outflows:
            amount = float(item.get("amount", 0.0))
            if amount <= 0:
                continue
            item_date = _parse_date(item.get("date", ""))
            if item_date is None:
                period_outflows += amount
            elif _in_period(item_date, period_start, period_end):
                period_outflows += amount

        net_change = round(period_inflows - period_outflows, 2)
        projected_end_balance = round(current_balance + net_change, 2)

        return {
            "status": "success",
            "current_balance": round(current_balance, 2),
            "period_inflows": round(period_inflows, 2),
            "period_outflows": round(period_outflows, 2),
            "net_change": net_change,
            "projected_end_balance": projected_end_balance,
        }
    except Exception as exc:
        return _fail(f"Cash position tracking failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime | None:
    """Parse a YYYY-MM-DD date string, returning None on failure."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _in_period(
    dt: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Check if a date falls within a period (inclusive)."""
    if dt is None:
        return True
    if start and dt < start:
        return False
    if end and dt > end:
        return False
    return True


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized module-level failure."""
    return {
        "status": "error",
        "error": reason,
    }
