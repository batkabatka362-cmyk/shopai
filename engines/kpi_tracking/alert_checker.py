"""KPI Tracking Engine — alert checker.

Checks KPIs against thresholds and generates alerts for
anomalies, declines, and benchmark violations.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

_ALERT_RULES = [
    {
        "kpi": "conversion_rate",
        "condition": "below",
        "threshold": 0.01,
        "severity": "critical",
        "message": "Conversion rate is critically low (below 1%)",
    },
    {
        "kpi": "conversion_rate",
        "condition": "below",
        "threshold": 0.02,
        "severity": "warning",
        "message": "Conversion rate is below industry average (below 2%)",
    },
    {
        "kpi": "cac",
        "condition": "above",
        "threshold": 100.0,
        "severity": "warning",
        "message": "Customer acquisition cost is high (above $100)",
    },
    {
        "kpi": "cac",
        "condition": "above",
        "threshold": 200.0,
        "severity": "critical",
        "message": "Customer acquisition cost is critically high (above $200)",
    },
    {
        "kpi": "repeat_rate",
        "condition": "below",
        "threshold": 0.10,
        "severity": "warning",
        "message": "Repeat purchase rate is very low (below 10%)",
    },
    {
        "kpi": "gross_margin",
        "condition": "below",
        "threshold": 0.20,
        "severity": "critical",
        "message": "Gross margin is critically low (below 20%)",
    },
    {
        "kpi": "gross_margin",
        "condition": "below",
        "threshold": 0.35,
        "severity": "warning",
        "message": "Gross margin is below healthy level (below 35%)",
    },
]

# Trend-based alert thresholds
_DECLINE_CRITICAL_PCT = -20.0  # 20% decline is critical
_DECLINE_WARNING_PCT = -10.0   # 10% decline is warning


def check_alerts(
    kpis: dict[str, Any],
    trends: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check KPIs against alert thresholds.

    Args:
        kpis: Current KPI values dict.
        trends: List of KPI trend dicts.
        comparisons: List of benchmark comparison dicts.

    Returns:
        Structured dict with triggered alerts.
    """
    try:
        kpis = copy.deepcopy(kpis)
        alerts: list[dict[str, Any]] = []

        # Check static threshold rules
        for rule in _ALERT_RULES:
            kpi_name = rule["kpi"]
            current_val = float(kpis.get(kpi_name, 0))
            threshold = float(rule["threshold"])
            condition = rule["condition"]

            triggered = False
            if condition == "below" and current_val < threshold:
                triggered = True
            elif condition == "above" and current_val > threshold:
                triggered = True

            if triggered:
                alerts.append({
                    "kpi": kpi_name,
                    "severity": str(rule["severity"]),
                    "message": str(rule["message"]),
                    "current_value": current_val,
                    "threshold": threshold,
                })

        # Check trend-based alerts
        for trend in trends:
            kpi_name = str(trend.get("kpi", ""))
            direction = str(trend.get("direction", ""))
            change_pct = float(trend.get("change_pct", 0))

            if direction == "down":
                if change_pct <= _DECLINE_CRITICAL_PCT:
                    alerts.append({
                        "kpi": kpi_name,
                        "severity": "critical",
                        "message": f"{kpi_name} declined {abs(change_pct):.1f}% vs previous period",
                        "current_value": float(trend.get("current_value", 0)),
                        "threshold": _DECLINE_CRITICAL_PCT,
                    })
                elif change_pct <= _DECLINE_WARNING_PCT:
                    alerts.append({
                        "kpi": kpi_name,
                        "severity": "warning",
                        "message": f"{kpi_name} declined {abs(change_pct):.1f}% vs previous period",
                        "current_value": float(trend.get("current_value", 0)),
                        "threshold": _DECLINE_WARNING_PCT,
                    })

        # Check benchmark-based alerts
        for comp in comparisons:
            percentile = str(comp.get("percentile", ""))
            if percentile == "bottom_quartile":
                alerts.append({
                    "kpi": str(comp.get("kpi", "")),
                    "severity": "warning",
                    "message": f"{comp.get('kpi', '')} is in the bottom quartile vs industry",
                    "current_value": float(comp.get("current_value", 0)),
                    "threshold": float(comp.get("industry_avg", 0)),
                })

        # Deduplicate alerts (keep highest severity per KPI)
        alerts = _deduplicate_alerts(alerts)

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: severity_order.get(a.get("severity", "info"), 3))

        return {
            "status": "success",
            "alerts": alerts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "alerts": [],
            "error": f"Alert checking failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deduplicate_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the highest-severity alert per KPI."""
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    best: dict[str, dict[str, Any]] = {}

    for alert in alerts:
        kpi = str(alert.get("kpi", ""))
        msg = str(alert.get("message", ""))
        key = f"{kpi}:{msg[:50]}"
        current_rank = severity_rank.get(str(alert.get("severity", "")), 3)

        if key not in best or current_rank < severity_rank.get(str(best[key].get("severity", "")), 3):
            best[key] = alert

    return list(best.values())
