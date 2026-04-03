"""Cash Flow Engine — payment term manager.

Manages receivables and payables: categorizes into aging buckets,
flags overdue items, and computes net receivables position.

Aging buckets: current (0-30), 30-day (31-60), 60-day (61-90), 90+ (91+).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


def manage_payment_terms(
    receivables: list[dict[str, Any]],
    payables: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze receivables and payables with aging classification.

    Categorizes each item into aging buckets based on days since
    issue_date (or days past due_date for overdue detection).

    Args:
        receivables: List of Receivable dicts.
        payables: List of Payable dicts.

    Returns:
        Structured dict with totals, aging breakdown, and overdue count.
    """
    try:
        receivables = copy.deepcopy(receivables)
        payables = copy.deepcopy(payables)
        today = datetime.utcnow()

        # Process receivables
        total_receivables = 0.0
        aging_receivables = {"current": 0.0, "30_day": 0.0, "60_day": 0.0, "90_plus": 0.0}
        overdue_count = 0

        for item in receivables:
            amount = float(item.get("amount", 0.0))
            total_receivables += amount

            due_date = _parse_date(item.get("due_date", ""))
            issue_date = _parse_date(item.get("issue_date", ""))

            # Overdue check
            if due_date and due_date < today:
                overdue_count += 1

            # Aging bucket based on days since issue
            ref_date = issue_date or due_date
            if ref_date:
                days_aged = (today - ref_date).days
            else:
                days_aged = 0

            bucket = _aging_bucket(days_aged)
            aging_receivables[bucket] += amount

        # Process payables
        total_payables = 0.0
        aging_payables = {"current": 0.0, "30_day": 0.0, "60_day": 0.0, "90_plus": 0.0}

        for item in payables:
            amount = float(item.get("amount", 0.0))
            total_payables += amount

            due_date = _parse_date(item.get("due_date", ""))
            issue_date = _parse_date(item.get("issue_date", ""))

            # Overdue payables also count
            if due_date and due_date < today:
                overdue_count += 1

            ref_date = issue_date or due_date
            if ref_date:
                days_aged = (today - ref_date).days
            else:
                days_aged = 0

            bucket = _aging_bucket(days_aged)
            aging_payables[bucket] += amount

        net_receivables = round(total_receivables - total_payables, 2)

        return {
            "status": "success",
            "total_receivables": round(total_receivables, 2),
            "total_payables": round(total_payables, 2),
            "net_receivables": net_receivables,
            "aging_receivables": {k: round(v, 2) for k, v in aging_receivables.items()},
            "aging_payables": {k: round(v, 2) for k, v in aging_payables.items()},
            "overdue_count": overdue_count,
        }
    except Exception as exc:
        return _fail(f"Payment term management failed: {exc}")


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


def _aging_bucket(days: int) -> str:
    """Classify a number of days into an aging bucket."""
    if days <= 30:
        return "current"
    elif days <= 60:
        return "30_day"
    elif days <= 90:
        return "60_day"
    else:
        return "90_plus"


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized module-level failure."""
    return {
        "status": "error",
        "error": reason,
    }
