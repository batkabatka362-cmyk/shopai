"""Cash Flow Engine — runway calculator.

Calculates how many months of runway remain based on current balance,
fixed costs, and average revenue. Determines risk level and estimates
zero-cash date.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def calculate_runway(
    current_balance: float,
    monthly_fixed_costs: float,
    avg_monthly_revenue: float,
) -> dict[str, Any]:
    """Calculate cash runway.

    Net monthly burn = fixed_costs - revenue. If revenue exceeds costs
    (negative burn), runway is infinite.

    Risk levels:
        >6 months  = healthy
        3-6 months = moderate
        <3 months  = critical

    Args:
        current_balance: Current cash balance.
        monthly_fixed_costs: Monthly fixed cost amount.
        avg_monthly_revenue: Average monthly revenue.

    Returns:
        Structured dict with runway calculations.
    """
    try:
        monthly_burn_rate = round(monthly_fixed_costs, 2)
        net_monthly_burn = round(monthly_fixed_costs - avg_monthly_revenue, 2)

        # If revenue covers costs, runway is infinite
        if net_monthly_burn <= 0:
            return {
                "status": "success",
                "monthly_burn_rate": monthly_burn_rate,
                "net_monthly_burn": net_monthly_burn,
                "months_of_runway": float("inf"),
                "runway_risk": "healthy",
                "zero_cash_date": None,
            }

        # Calculate months of runway
        if current_balance <= 0:
            months_of_runway = 0.0
        else:
            months_of_runway = round(current_balance / net_monthly_burn, 1)

        # Determine risk level
        if months_of_runway > 6:
            runway_risk = "healthy"
        elif months_of_runway >= 3:
            runway_risk = "moderate"
        else:
            runway_risk = "critical"

        # Estimate zero cash date
        if months_of_runway > 0:
            days_until_zero = int(months_of_runway * 30.44)  # avg days per month
            zero_date = datetime.utcnow() + timedelta(days=days_until_zero)
            zero_cash_date = zero_date.strftime("%Y-%m-%d")
        else:
            zero_cash_date = datetime.utcnow().strftime("%Y-%m-%d")

        return {
            "status": "success",
            "monthly_burn_rate": monthly_burn_rate,
            "net_monthly_burn": net_monthly_burn,
            "months_of_runway": months_of_runway,
            "runway_risk": runway_risk,
            "zero_cash_date": zero_cash_date,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": f"Runway calculation failed: {exc}",
        }
