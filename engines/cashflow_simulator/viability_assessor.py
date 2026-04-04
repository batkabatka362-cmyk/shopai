"""Cashflow Simulator Engine — viability assessor.

Assesses business viability, runway, and break-even timing.
"""
from __future__ import annotations

from typing import Any


def assess_viability(
    scenarios: dict[str, dict[str, Any]],
    current_balance: float,
    monthly_costs: float,
) -> dict[str, Any]:
    """Assess business viability from scenario projections."""
    try:
        expected = scenarios.get("expected", {})
        projections = expected.get("projections", [])

        # Calculate runway (months until balance goes negative)
        runway_months = len(projections)
        for proj in projections:
            if float(proj.get("balance", 0)) < 0:
                runway_months = int(proj.get("month", 0)) - 1
                break

        # Find break-even month (first month with positive net)
        break_even_month = 0
        for proj in projections:
            if float(proj.get("net", 0)) > 0:
                break_even_month = int(proj.get("month", 0))
                break

        # Risk assessment
        notes: list[str] = []
        worst = scenarios.get("worst", {})
        worst_final = float(worst.get("final_balance", 0))

        if runway_months < 3:
            risk = "critical"
            notes.append("Less than 3 months runway — immediate action required")
        elif runway_months < 6:
            risk = "high"
            notes.append("Less than 6 months runway — cost reduction or funding needed")
        elif worst_final < 0:
            risk = "moderate"
            notes.append("Worst-case scenario results in negative balance")
        else:
            risk = "low"
            notes.append("Healthy cash flow across all scenarios")

        if break_even_month == 0:
            notes.append("Business does not reach profitability in projection period")
        elif break_even_month > 6:
            notes.append(f"Break-even expected in month {break_even_month} — monitor closely")

        burn_rate = round(monthly_costs, 2)
        if current_balance > 0 and burn_rate > 0:
            simple_runway = round(current_balance / burn_rate, 1)
            notes.append(f"Simple burn-rate runway: {simple_runway} months")

        viability = {
            "runway_months": runway_months,
            "break_even_month": break_even_month,
            "risk": risk,
            "notes": notes,
        }

        return {"status": "success", "viability": viability}
    except Exception as exc:
        return {"status": "error", "viability": {}, "error": f"Viability assessment failed: {exc}"}
