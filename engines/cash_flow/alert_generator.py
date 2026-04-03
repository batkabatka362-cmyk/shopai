"""Cash Flow Engine — alert generator.

Generates actionable cash flow alerts based on runway, cash position,
and payment term analysis.

Alert types: low_balance, runway_critical, runway_moderate,
             overdue_receivable, large_payable_due.
Severity levels: critical, high, medium, low.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any


# Thresholds
_LOW_BALANCE_THRESHOLD = 5000.0
_LARGE_PAYABLE_THRESHOLD = 1000.0
_LARGE_PAYABLE_WINDOW_DAYS = 7


def generate_alerts(
    runway: dict[str, Any],
    cash_position: dict[str, Any],
    payment_terms: dict[str, Any],
    payables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate cash flow alerts from analysis results.

    Scans runway, cash position, and payment terms for actionable
    conditions and produces prioritized alerts sorted by severity.

    Args:
        runway: Result dict from runway_calculator.
        cash_position: Result dict from cash_position_tracker.
        payment_terms: Result dict from payment_term_manager.
        payables: Original payables list (for large payable due detection).

    Returns:
        Structured dict with list of CashAlert dicts.
    """
    try:
        runway = copy.deepcopy(runway)
        cash_position = copy.deepcopy(cash_position)
        payment_terms = copy.deepcopy(payment_terms)
        payables = copy.deepcopy(payables or [])

        alerts: list[dict[str, Any]] = []
        today = datetime.utcnow()

        # --- Low balance alert ---
        current_balance = float(cash_position.get("current_balance", 0.0))
        projected_balance = float(cash_position.get("projected_end_balance", current_balance))

        if current_balance < _LOW_BALANCE_THRESHOLD:
            alerts.append({
                "alert_type": "low_balance",
                "severity": "critical",
                "message": (
                    f"Current cash balance is ${current_balance:,.2f}, "
                    f"below the ${_LOW_BALANCE_THRESHOLD:,.2f} threshold."
                ),
                "recommended_action": (
                    "Accelerate receivable collections, defer non-essential "
                    "spending, and review credit line options."
                ),
            })
        elif projected_balance < _LOW_BALANCE_THRESHOLD:
            alerts.append({
                "alert_type": "low_balance",
                "severity": "high",
                "message": (
                    f"Projected end-of-period balance is ${projected_balance:,.2f}, "
                    f"which will fall below the ${_LOW_BALANCE_THRESHOLD:,.2f} threshold."
                ),
                "recommended_action": (
                    "Review upcoming expenses and prioritize receivable "
                    "collections to maintain adequate cash reserves."
                ),
            })

        # --- Runway critical alert ---
        runway_risk = str(runway.get("runway_risk", ""))
        months_of_runway = runway.get("months_of_runway", float("inf"))
        zero_cash_date = runway.get("zero_cash_date")

        if runway_risk == "critical":
            date_msg = f" Estimated zero-cash date: {zero_cash_date}." if zero_cash_date else ""
            alerts.append({
                "alert_type": "runway_critical",
                "severity": "critical",
                "message": (
                    f"Cash runway is critically low at {months_of_runway} months.{date_msg}"
                ),
                "recommended_action": (
                    "Immediately reduce burn rate, pursue emergency funding, "
                    "and negotiate extended payment terms with vendors."
                ),
            })

        # --- Runway moderate alert ---
        if runway_risk == "moderate":
            alerts.append({
                "alert_type": "runway_moderate",
                "severity": "high",
                "message": (
                    f"Cash runway is moderate at {months_of_runway} months. "
                    f"Action recommended within 30 days."
                ),
                "recommended_action": (
                    "Begin exploring funding options, optimize costs, "
                    "and accelerate revenue growth initiatives."
                ),
            })

        # --- Overdue receivable alert ---
        overdue_count = int(payment_terms.get("overdue_count", 0))
        if overdue_count > 0:
            aging_recv = payment_terms.get("aging_receivables", {})
            overdue_amount = float(aging_recv.get("60_day", 0.0)) + float(aging_recv.get("90_plus", 0.0))
            alerts.append({
                "alert_type": "overdue_receivable",
                "severity": "high" if overdue_count >= 3 else "medium",
                "message": (
                    f"{overdue_count} overdue receivable(s) detected "
                    f"with ${overdue_amount:,.2f} in aged buckets (60+ days)."
                ),
                "recommended_action": (
                    "Initiate collection procedures for overdue accounts. "
                    "Consider offering early payment discounts for current receivables."
                ),
            })

        # --- Large payable due soon ---
        deadline = today + timedelta(days=_LARGE_PAYABLE_WINDOW_DAYS)
        for payable in payables:
            amount = float(payable.get("amount", 0.0))
            due_str = payable.get("due_date", "")
            status = str(payable.get("status", "")).lower()

            if status in ("paid", "settled"):
                continue
            if amount < _LARGE_PAYABLE_THRESHOLD:
                continue

            due_date = _parse_date(due_str)
            if due_date is None:
                continue

            if today <= due_date <= deadline:
                vendor = payable.get("vendor", "Unknown")
                days_until = (due_date - today).days
                alerts.append({
                    "alert_type": "large_payable_due",
                    "severity": "medium",
                    "message": (
                        f"${amount:,.2f} payable to {vendor} due in "
                        f"{days_until} day(s) ({due_str})."
                    ),
                    "recommended_action": (
                        "Ensure sufficient funds are available. Consider "
                        "negotiating payment terms if cash is tight."
                    ),
                })

        # Sort by severity: critical > high > medium > low
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 4))

        return {
            "status": "success",
            "alerts": alerts,
            "total_alerts": len(alerts),
        }
    except Exception as exc:
        return _fail(f"Alert generation failed: {exc}")


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


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized module-level failure."""
    return {
        "status": "error",
        "alerts": [],
        "error": reason,
    }
