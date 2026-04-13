"""Seasonal Risk — business rules and policy constraints.

Hard rules:
  - Highly seasonal products require 4 months cash reserve.
  - Fad products: max 2-month inventory commitment.
  - Never launch a seasonal product off-peak.
  - Weather-dependent products need a bad-weather contingency plan.
"""
from __future__ import annotations

from typing import Any


def evaluate_rules(context: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all seasonal risk rules against the provided context.

    Returns {passed: bool, violations: [...], warnings: [...]}.
    """
    violations: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    classification = context.get("classification", "non_seasonal")
    cash_reserve_months = context.get("cash_reserve_months", 0)
    inventory_months = context.get("inventory_months_on_hand", 0)
    launch_month = context.get("launch_month")
    peak_months = context.get("peak_months", [])
    trough_months = context.get("trough_months", [])
    weather_dependent = context.get("weather_dependent", False)
    has_contingency = context.get("has_weather_contingency", False)
    trend_months = context.get("trend_duration_months", 0)

    # Rule 1: Highly seasonal products require 4 months cash reserve
    if classification == "highly_seasonal" and cash_reserve_months < 4:
        violations.append({
            "rule": "cash_reserve_requirement",
            "message": (
                f"Highly seasonal products require 4 months cash reserve, "
                f"but only {cash_reserve_months} months available."
            ),
            "severity": "critical",
        })

    # Rule 2: Fad products — max 2 months inventory
    if classification == "fad" and inventory_months > 2:
        violations.append({
            "rule": "fad_inventory_limit",
            "message": (
                f"Fad products must not hold more than 2 months inventory. "
                f"Currently holding {inventory_months} months."
            ),
            "severity": "critical",
        })

    # Rule 3: Do not launch seasonal products off-peak
    if launch_month and peak_months and classification in ("highly_seasonal", "moderate_seasonal"):
        ramp_months = [(m - 2) % 12 or 12 for m in peak_months]
        acceptable = set(peak_months) | set(ramp_months)
        if launch_month not in acceptable:
            violations.append({
                "rule": "off_peak_launch",
                "message": (
                    f"Launching a {classification} product in month {launch_month} "
                    f"is off-peak. Peak months: {peak_months}. "
                    f"Launch during ramp-up or peak instead."
                ),
                "severity": "high",
            })

    # Rule 4: Weather-dependent products need contingency
    if weather_dependent and not has_contingency:
        warnings.append({
            "rule": "weather_contingency_missing",
            "message": "Weather-dependent product lacks a bad-weather contingency plan.",
            "severity": "medium",
        })

    # Rule 5: Moderate seasonal should hold at least 3 months reserve
    if classification == "moderate_seasonal" and cash_reserve_months < 3:
        warnings.append({
            "rule": "moderate_cash_reserve",
            "message": (
                f"Moderate seasonal products should hold 3 months reserve; "
                f"only {cash_reserve_months} months available."
            ),
            "severity": "medium",
        })

    # Rule 6: Fad products with short trend need immediate exit plan
    if classification == "fad" and trend_months > 0 and trend_months < 3:
        warnings.append({
            "rule": "fad_exit_urgency",
            "message": (
                f"Fad product with only {trend_months} months of trend data. "
                f"Prepare exit strategy immediately."
            ),
            "severity": "high",
        })

    # Rule 7: Trough month launch warning
    if launch_month and launch_month in trough_months:
        violations.append({
            "rule": "trough_launch",
            "message": (
                f"Month {launch_month} is a demand trough for this category. "
                f"Expect minimal revenue for weeks or months after launch."
            ),
            "severity": "high",
        })

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "rules_checked": 7,
    }
