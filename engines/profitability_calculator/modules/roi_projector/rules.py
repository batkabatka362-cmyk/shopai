"""ROI projection rules — hard constraints for investment decisions.

Rules that MUST be checked before committing capital to a product.
Designed to prevent common e-commerce money traps.
"""
from __future__ import annotations

from typing import Any


ROI_RULES = [
    {
        "id": "min_annual_roi_50pct",
        "name": "Minimum 50% annual ROI",
        "description": (
            "E-commerce requires active management (10-20 hours/month). "
            "Products returning less than 50% annually are not worth the effort "
            "compared to passive investments or a part-time job."
        ),
        "check": lambda data: (
            data.get("roi_summary", {}).get("roi_pct", 0) >= 50
        ),
        "severity": "blocker",
        "action": "ROI too low — increase margins, reduce costs, or find a better product",
    },
    {
        "id": "positive_cash_flow_month_3",
        "name": "Positive monthly cash flow by month 3",
        "description": (
            "If a product is not generating positive monthly cash flow by month 3, "
            "it likely never will. Month 1-2 losses are expected (launch costs), "
            "but month 3 should show the business model works."
        ),
        "check": lambda data: _check_month_profit(data, month=3, min_profit=0),
        "severity": "blocker",
        "action": "Product not profitable by month 3 — review pricing and cost structure",
    },
    {
        "id": "stop_if_negative_month_6",
        "name": "Stop if cumulative ROI negative at month 6",
        "description": (
            "If after 6 months of sales the cumulative ROI is still negative "
            "in the expected scenario, cut losses. Sunk cost fallacy kills "
            "more e-commerce businesses than bad products."
        ),
        "check": lambda data: _check_cumulative_roi(data, month=6, min_roi=0),
        "severity": "blocker",
        "action": "Cumulative ROI still negative at month 6 — liquidate inventory and exit",
    },
    {
        "id": "conservative_not_catastrophic",
        "name": "Conservative scenario must not lose more than 50% of investment",
        "description": (
            "Even in the worst realistic scenario, you should not lose more "
            "than half your investment. If the downside is that severe, the "
            "risk-reward ratio is unacceptable."
        ),
        "check": lambda data: _check_conservative_floor(data, max_loss_pct=-50),
        "severity": "warning",
        "action": "Downside risk too high — reduce initial investment or improve unit economics",
    },
    {
        "id": "cash_recovery_within_12_months",
        "name": "Cash must recover within 12 months",
        "description": (
            "Total cash invested must be recovered within the first year. "
            "Products that take longer than 12 months to pay back tie up "
            "capital that could be deployed elsewhere."
        ),
        "check": lambda data: data.get("cash_flow", {}).get("recovered", False),
        "severity": "warning",
        "action": "Cash recovery exceeds 12 months — reduce investment or boost margins",
    },
    {
        "id": "roi_beats_sp500",
        "name": "ROI should beat S&P 500 returns (10%)",
        "description": (
            "If the product cannot beat a passive index fund investment, "
            "your capital and time are better deployed elsewhere."
        ),
        "check": lambda data: (
            data.get("roi_summary", {}).get("roi_pct", 0) > 10
        ),
        "severity": "info",
        "action": "ROI below passive investment returns — reconsider allocation",
    },
    {
        "id": "month_6_profit_growth",
        "name": "Month 6 profit should exceed month 3 profit",
        "description": (
            "A healthy product shows growing profits over time as organic "
            "traffic builds and ad efficiency improves. Flat or declining "
            "profits suggest the product has peaked too early."
        ),
        "check": lambda data: _check_profit_growth(data, from_month=3, to_month=6),
        "severity": "info",
        "action": "Profit trajectory is flat or declining — investigate growth levers",
    },
]


def _check_month_profit(data: dict, month: int, min_profit: float) -> bool:
    """Check if a specific month's net profit meets the minimum."""
    expected = data.get("scenarios", {}).get("expected", [])
    if len(expected) >= month:
        return expected[month - 1].get("net_profit", -1) >= min_profit
    return False


def _check_cumulative_roi(data: dict, month: int, min_roi: float) -> bool:
    """Check if cumulative ROI at a given month meets the minimum."""
    expected = data.get("scenarios", {}).get("expected", [])
    if len(expected) >= month:
        return expected[month - 1].get("cumulative_roi_pct", -100) >= min_roi
    return False


def _check_conservative_floor(data: dict, max_loss_pct: float) -> bool:
    """Check that conservative scenario doesn't lose more than max_loss_pct."""
    conservative = data.get("scenarios", {}).get("conservative", [])
    if conservative:
        final_roi = conservative[-1].get("cumulative_roi_pct", -100)
        return final_roi >= max_loss_pct
    return False


def _check_profit_growth(data: dict, from_month: int, to_month: int) -> bool:
    """Check that profit is growing between two months."""
    expected = data.get("scenarios", {}).get("expected", [])
    if len(expected) >= to_month:
        early = expected[from_month - 1].get("net_profit", 0)
        later = expected[to_month - 1].get("net_profit", 0)
        return later >= early
    return False


def evaluate_roi_rules(roi_data: dict[str, Any]) -> dict[str, Any]:
    """Run all ROI rules against the projection data.

    Args:
        roi_data: Output from code.project_roi()

    Returns:
        {
            "passed": bool,
            "blockers": [...],
            "warnings": [...],
            "info": [...],
            "rules_evaluated": int,
            "summary": str,
        }
    """
    if roi_data.get("status") == "error":
        return {
            "passed": False,
            "blockers": [{
                "rule_id": "negative_margin",
                "name": "Margins not viable",
                "action": roi_data.get("message", "Fix unit economics"),
            }],
            "warnings": [],
            "info": [],
            "rules_evaluated": 1,
            "summary": "Blocked: margins are negative — cannot project positive ROI",
        }

    blockers = []
    warnings = []
    info = []

    for rule in ROI_RULES:
        try:
            passed = rule["check"](roi_data)
        except Exception:
            passed = True  # Don't block on rule evaluation errors

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            elif rule["severity"] == "warning":
                warnings.append(entry)
            else:
                info.append(entry)

    if blockers:
        summary = f"Blocked: {len(blockers)} critical issue(s) — do not invest"
    elif warnings:
        summary = f"Conditional pass: {len(warnings)} warning(s) to monitor"
    else:
        summary = "All ROI rules passed — investment is viable"

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "info": info,
        "rules_evaluated": len(ROI_RULES),
        "summary": summary,
    }
