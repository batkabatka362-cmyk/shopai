"""Cash Flow Engine — runway calculator.

Calculates cash runway: months until zero cash, burn rate,
risk classification, and projected zero-cash date.

Risk levels: healthy (>6mo), moderate (3-6mo), critical (<3mo).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any


def calculate_runway(
    current_balance: float,
    monthly_fixed_costs: float,
    avg_monthly_revenue: float,
) -> dict[str, Any]:
    """Calculate cash runway and burn metrics.

    Net monthly burn = fixed_costs - revenue. If revenue exceeds costs,
    runway is effectively infinite (reported as -1).

    Args:
        current_balance: Current cash on hand.
        monthly_fixed_costs: Total monthly fixed costs.
        avg_monthly_revenue: Average monthly revenue.

    Returns:
        Structured dict with burn rate, runway, risk level, and zero-cash date.
    """
    try:
        monthly_burn_rate = float(monthly_fixed_costs)
        net_monthly_burn = monthly_burn_rate - float(avg_monthly_revenue)

        # If net burn is zero or negative (profitable), runway is infinite
        if net_monthly_burn <= 0:
            return {
                "status": "success",
                "monthly_burn_rate": round(monthly_burn_rate, 2),
                "net_monthly_burn": round(net_monthly_burn, 2),
                "months_of_runway": float("inf"),
                "runway_risk": "healthy",
                "zero_cash_date": None,
            }

        # Calculate months of runway
        months_of_runway = current_balance / net_monthly_burn

        # Risk classification
        if months_of_runway > 6:
            runway_risk = "healthy"
        elif months_of_runway >= 3:
            runway_risk = "moderate"
        else:
            runway_risk = "critical"

        # Estimate zero-cash date
        days_until_zero = months_of_runway * 30.44  # average days per month
        zero_cash_dt = datetime.utcnow() + timedelta(days=days_until_zero)
        zero_cash_date = zero_cash_dt.strftime("%Y-%m-%d")

        return {
            "status": "success",
            "monthly_burn_rate": round(monthly_burn_rate, 2),
            "net_monthly_burn": round(net_monthly_burn, 2),
            "months_of_runway": round(months_of_runway, 2),
            "runway_risk": runway_risk,
            "zero_cash_date": zero_cash_date,
        }
    except Exception as exc:
        return _fail(f"Runway calculation failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardized module-level failure."""
    return {
        "status": "error",
        "error": reason,
    }
