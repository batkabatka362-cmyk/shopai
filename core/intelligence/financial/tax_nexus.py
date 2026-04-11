"""Tax nexus analysis — US state economic nexus thresholds.

Tracks which states you have tax obligations in based on revenue thresholds.
20 major US states encoded with revenue threshold, transaction count, and tax rate.
"""
from __future__ import annotations

from typing import Any


# US Economic Nexus Thresholds (top 20 states)
TAX_NEXUS_THRESHOLDS = {
    "CA": {"revenue": 500000, "transactions": 0, "rate": 0.0725},
    "TX": {"revenue": 500000, "transactions": 0, "rate": 0.0625},
    "NY": {"revenue": 500000, "transactions": 100, "rate": 0.08},
    "FL": {"revenue": 100000, "transactions": 0, "rate": 0.06},
    "IL": {"revenue": 100000, "transactions": 200, "rate": 0.0625},
    "PA": {"revenue": 100000, "transactions": 0, "rate": 0.06},
    "OH": {"revenue": 100000, "transactions": 200, "rate": 0.0575},
    "GA": {"revenue": 100000, "transactions": 200, "rate": 0.04},
    "NC": {"revenue": 100000, "transactions": 200, "rate": 0.0475},
    "MI": {"revenue": 100000, "transactions": 200, "rate": 0.06},
    "NJ": {"revenue": 100000, "transactions": 200, "rate": 0.06625},
    "VA": {"revenue": 100000, "transactions": 200, "rate": 0.053},
    "WA": {"revenue": 100000, "transactions": 0, "rate": 0.065},
    "MA": {"revenue": 100000, "transactions": 0, "rate": 0.0625},
    "AZ": {"revenue": 100000, "transactions": 0, "rate": 0.056},
    "CO": {"revenue": 100000, "transactions": 0, "rate": 0.029},
    "TN": {"revenue": 100000, "transactions": 0, "rate": 0.07},
    "IN": {"revenue": 100000, "transactions": 0, "rate": 0.07},
    "MO": {"revenue": 100000, "transactions": 0, "rate": 0.04225},
    "WI": {"revenue": 100000, "transactions": 0, "rate": 0.05},
}


def analyze_tax_nexus(revenue_by_state: dict[str, float]) -> dict[str, Any]:
    """Analyze tax nexus obligations across US states."""
    if not revenue_by_state:
        return {"status": "no_data", "note": "Provide revenue_by_state for nexus analysis"}

    nexus_states = []
    non_nexus_states = []
    total_liability = 0

    for state, threshold in TAX_NEXUS_THRESHOLDS.items():
        state_revenue = revenue_by_state.get(state, 0)
        has_nexus = state_revenue >= threshold["revenue"]

        if has_nexus:
            tax = round(state_revenue * threshold["rate"], 2)
            total_liability += tax
            nexus_states.append({
                "state": state,
                "revenue": state_revenue,
                "threshold": threshold["revenue"],
                "rate": threshold["rate"],
                "estimated_tax": tax,
                "over_by": round(state_revenue - threshold["revenue"], 2),
            })
        elif state_revenue > threshold["revenue"] * 0.7:
            non_nexus_states.append({
                "state": state,
                "revenue": state_revenue,
                "threshold": threshold["revenue"],
                "pct_to_nexus": round(state_revenue / threshold["revenue"] * 100, 1),
                "warning": "Approaching nexus threshold",
            })

    return {
        "nexus_states": nexus_states,
        "approaching_nexus": non_nexus_states,
        "total_estimated_tax": round(total_liability, 2),
        "states_with_nexus": len(nexus_states),
        "states_approaching": len(non_nexus_states),
        "action_needed": len(nexus_states) > 0,
    }
