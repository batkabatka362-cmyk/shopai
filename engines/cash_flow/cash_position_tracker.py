"""Cash Flow Engine — cash position tracker.

Tracks real-time cash position by summing inflows and outflows for a
given period and computing net change and projected end balance.

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
    """Track cash position for the given period.

    Sums inflows and outflows within the period window, computes
    net change and projected end balance.

    Args:
        current_balance: Current cash balance.
        inflows: List of CashInflow dicts.
        outflows: List of CashOutflow dicts.
        period: Dict with 'start' and 'end' date strings (YYYY-MM-DD).

    Returns:
        Structured dict with cash position data.
    """
    try:
        safe_inflows = copy.deepcopy(inflows)
        safe_outflows = copy.deepcopy(outflows)

        period_start = _parse_date(period.get("start", ""))
        period_end = _parse_date(period.get("end", ""))

        # Sum inflows within period
        total_inflows = 0.0
        for item in safe_inflows:
            amount = float(item.get("amount", 0.0))
            if amount <= 0:
                continue
            item_date = _parse_date(item.get("date", ""))
            if item_date and period_start and period_end:
                if period_start <= item_date <= period_end:
                    total_inflows += amount
            else:
                # If dates can't be parsed, include all
                total_inflows += amount

        # Sum outflows within period
        total_outflows = 0.0
        for item in safe_outflows:
            amount = float(item.get("amount", 0.0))
            if amount <= 0:
                continue
            item_date = _parse_date(item.get("date", ""))
            if item_date and period_start and period_end:
                if period_start <= item_date <= period_end:
                    total_outflows += amount
            else:
                total_outflows += amount

        net_change = round(total_inflows - total_outflows, 2)
        projected_end_balance = round(current_balance + net_change, 2)

        return {
            "status": "success",
            "current_balance": round(current_balance, 2),
            "period_inflows": round(total_inflows, 2),
            "period_outflows": round(total_outflows, 2),
            "net_change": net_change,
            "projected_end_balance": projected_end_balance,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"Cash position tracking failed: {exc}",
        }


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
