"""Cash Flow Engine — alert generator.

Generates actionable alerts based on runway status, cash position,
and payment term analysis.

Alert types: low_balance, runway_critical, runway_moderate,
             overdue_receivable, large_payable_due.
Severity levels: critical, high, medium, low, info.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_LOW_BALANCE_THRESHOLD = 5000.0
_LARGE_PAYABLE_THRESHOLD = 1000.0


def generate_alerts(
    runway: dict[str, Any],
    cash_position: dict[str, Any],
    payment_terms: dict[str, Any],
) -> dict[str, Any]:
    """Generate cash flow alerts.

    Scans runway, cash position, and payment term data for actionable
    conditions and produces prioritized alerts sorted by severity.

    Args:
        runway: Runway calculation dict from runway_calculator.
        cash_position: Cash position dict from cash_position_tracker.
        payment_terms: Payment terms dict from payment_term_manager.

    Returns:
        Structured dict with list of CashAlert dicts.
    """
    try:
        safe_runway = copy.deepcopy(runway)
        safe_position = copy.deepcopy(cash_position)
        safe_terms = copy.deepcopy(payment_terms)

        alerts: list[dict[str, Any]] = []

        # --- Low balance alert ---
        current_balance = float(safe_position.get("current_balance", 0.0))
        projected_end = float(safe_position.get("projected_end_balance", current_balance))

        if current_balance < _LOW_BALANCE_THRESHOLD:
            alerts.append({
                "alert_type": "low_balance",
                "severity": "critical",
                "message": (
                    f"Current cash balance is ${current_balance:,.2f}, "
                    f"below the ${_LOW_BALANCE_THRESHOLD:,.2f} threshold."
                ),
                "recommended_action": (
                    "Accelerate receivables collection. Delay non-essential "
                    "expenses. Consider emergency credit line."
                ),
            })
        elif projected_end < _LOW_BALANCE_THRESHOLD:
            alerts.append({
                "alert_type": "low_balance",
                "severity": "high",
                "message": (
                    f"Projected end balance is ${projected_end:,.2f}, "
                    f"which will fall below ${_LOW_BALANCE_THRESHOLD:,.2f}."
                ),
                "recommended_action": (
                    "Review upcoming outflows and defer where possible. "
                    "Accelerate expected inflows."
                ),
            })

        # --- Runway critical alert ---
        runway_risk = str(safe_runway.get("runway_risk", ""))
        months_of_runway = safe_runway.get("months_of_runway", float("inf"))
        zero_cash_date = safe_runway.get("zero_cash_date")

        if runway_risk == "critical":
            date_msg = f" Estimated zero-cash date: {zero_cash_date}." if zero_cash_date else ""
            alerts.append({
                "alert_type": "runway_critical",
                "severity": "critical",
                "message": (
                    f"Cash runway is critically low at {months_of_runway} months.{date_msg}"
                ),
                "recommended_action": (
                    "Immediate cost reduction required. Explore emergency funding, "
                    "credit facilities, or revenue acceleration."
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
                    "Develop a cash conservation plan. Review discretionary "
                    "spending and explore additional revenue streams."
                ),
            })

        # --- Overdue receivable alert ---
        overdue_count = int(safe_terms.get("overdue_count", 0))
        aging_receivables = safe_terms.get("aging_receivables", {})
        overdue_amount = (
            float(aging_receivables.get("30_day", 0.0))
            + float(aging_receivables.get("60_day", 0.0))
            + float(aging_receivables.get("90_plus", 0.0))
        )

        if overdue_count > 0:
            alerts.append({
                "alert_type": "overdue_receivable",
                "severity": "high" if overdue_count >= 3 else "medium",
                "message": (
                    f"{overdue_count} receivable(s) are overdue, "
                    f"totaling approximately ${overdue_amount:,.2f}."
                ),
                "recommended_action": (
                    "Follow up with customers on overdue invoices. "
                    "Consider offering early payment discounts or "
                    "engaging collections for 90+ day items."
                ),
            })

        # --- Large payable due soon alert ---
        aging_payables = safe_terms.get("aging_payables", {})
        current_payables = float(aging_payables.get("current", 0.0))

        if current_payables > _LARGE_PAYABLE_THRESHOLD:
            alerts.append({
                "alert_type": "large_payable_due",
                "severity": "medium",
                "message": (
                    f"${current_payables:,.2f} in payables due within "
                    f"the current period (exceeds ${_LARGE_PAYABLE_THRESHOLD:,.2f} threshold)."
                ),
                "recommended_action": (
                    "Ensure sufficient funds for upcoming payments. "
                    "Negotiate extended terms if cash is tight."
                ),
            })

        # Sort alerts by severity: critical > high > medium > low > info
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 5))

        return {
            "status": "success",
            "alerts": alerts,
            "total_alerts": len(alerts),
        }
    except Exception as exc:
        return {
            "status": "error",
            "alerts": [],
            "error": f"Alert generation failed: {exc}",
        }
