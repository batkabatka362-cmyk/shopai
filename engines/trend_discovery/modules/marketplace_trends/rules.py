"""Marketplace trends rules — constraints on following bestseller trends."""
from __future__ import annotations
from typing import Any

RULES = [
    {"id": "no_exact_copy", "name": "No exact product copy", "description": "Don't replicate exact bestseller (IP/trademark risk)", "check": lambda d: not d.get("is_exact_copy", False), "severity": "blocker", "action": "Create improved/differentiated version, not exact copy"},
    {"id": "cross_platform", "name": "Cross-platform verification", "description": "Verify trend on 2+ marketplaces before committing", "check": lambda d: d.get("platforms_confirmed", 1) >= 2 or d.get("confidence", "") == "low", "severity": "warning", "action": "Single-platform trend — verify on Amazon, Etsy, or Google Shopping"},
    {"id": "not_seasonal_spike", "name": "Seasonal spike check", "description": "Ensure trend isn't just seasonal unless you're prepared", "check": lambda d: not d.get("seasonal_only", False) or d.get("seasonal_prep_done", False), "severity": "warning", "action": "Seasonal product — ensure inventory timing and off-season plan"},
    {"id": "min_reviews", "name": "Minimum review proof", "description": "Category must have products with 50+ reviews (proven demand)", "check": lambda d: d.get("avg_review_count", 0) >= 50 or d.get("is_new_category", False), "severity": "warning", "action": "Low review count — demand may be unproven"},
    {"id": "margin_viable", "name": "Margin viability", "description": "Estimated margin must be >25% after marketplace fees", "check": lambda d: d.get("estimated_margin", 50) >= 25, "severity": "blocker", "action": "Margin too thin after fees — not viable"},
]

def evaluate_rules(trend_data: dict[str, Any]) -> dict[str, Any]:
    blockers, warnings = [], []
    for rule in RULES:
        try:
            passed = rule["check"](trend_data)
        except Exception:
            passed = True
        if not passed:
            entry = {"rule_id": rule["id"], "name": rule["name"], "action": rule["action"]}
            if rule["severity"] == "blocker": blockers.append(entry)
            else: warnings.append(entry)
    return {"passed": len(blockers) == 0, "blockers": blockers, "warnings": warnings, "rules_evaluated": len(RULES)}
