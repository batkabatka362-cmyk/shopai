"""Market trends rules — hard constraints for trend-based decisions.

Rules prevent chasing bad trends or entering at the wrong time.
"""
from __future__ import annotations

from typing import Any


RULES = [
    {
        "id": "no_declining_trends",
        "name": "No declining markets",
        "description": "Do not enter markets with trend score below -20",
        "check": lambda data: data.get("trend_score", 0) >= -20,
        "severity": "blocker",
        "action": "Reject — market is declining",
    },
    {
        "id": "min_signal_count",
        "name": "Minimum signal diversity",
        "description": "Need at least 2 confirming signals to trust a trend",
        "check": lambda data: data.get("signal_count", 0) >= 2,
        "severity": "warning",
        "action": "Insufficient data — wait for more signals before committing",
    },
    {
        "id": "fad_protection",
        "name": "Fad protection",
        "description": "Reject single-channel spikes (e.g., social only, no search/review)",
        "check": lambda data: _check_multi_channel(data),
        "severity": "warning",
        "action": "Possible fad — only 1 signal channel active",
    },
    {
        "id": "not_too_late",
        "name": "Timing check",
        "description": "Trend should not already be in mature/declining phase",
        "check": lambda data: data.get("trend_level") not in ("stable", "declining", "dying"),
        "severity": "warning",
        "action": "Market may be saturated — differentiation critical",
    },
    {
        "id": "confidence_minimum",
        "name": "Data confidence",
        "description": "Confidence must be at least 'medium' to make decisions",
        "check": lambda data: data.get("confidence") in ("medium", "high"),
        "severity": "warning",
        "action": "Low confidence — collect more data before deciding",
    },
]


def evaluate_rules(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all trend rules against data."""
    blockers = []
    warnings = []

    for rule in RULES:
        try:
            passed = rule["check"](trend_data)
        except Exception:
            passed = True

        if not passed:
            entry = {
                "rule_id": rule["id"],
                "name": rule["name"],
                "description": rule["description"],
                "action": rule["action"],
            }
            if rule["severity"] == "blocker":
                blockers.append(entry)
            else:
                warnings.append(entry)

    return {
        "passed": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "rules_evaluated": len(RULES),
    }


def _check_multi_channel(data: dict[str, Any]) -> bool:
    """Check that trend has multi-channel confirmation."""
    components = data.get("components", {})
    strong_channels = 0
    for key, comp in components.items():
        if isinstance(comp, dict) and comp.get("score", 0) > 30:
            strong_channels += 1
    return strong_channels >= 2
