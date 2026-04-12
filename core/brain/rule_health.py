"""Rule Health Checker — monitors and scores rule effectiveness.

ADDITIVE ONLY — does not modify or delete existing rules.
Adds health metadata and recommendations.

Checks:
  - Zero-success rules (used many times, never succeeded)
  - Over-relied rules (single rule dominates decisions)
  - Stale rules (not used recently)
  - Conflicting rules (prefer + avoid in same category)
"""
from __future__ import annotations

import threading as _threading
import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("brain.rule_health")


class RuleHealthChecker:
    """Monitors rule effectiveness without modifying rules."""

    def __init__(self) -> None:
        self._last_check: dict[str, Any] = {}

    def check(self) -> dict[str, Any]:
        """Run full rule health check. Returns report only — no mutations."""
        try:
            from core.memory.unified_memory import get_unified_memory
            mi = get_unified_memory().get_memory_intelligence()
        except Exception:
            return {"status": "unavailable"}

        rules = mi.get_rules()
        if not rules:
            return {"status": "no_rules", "total": 0}

        zero_success = []
        over_relied = []
        stale = []
        conflicting = []
        healthy = []

        total_uses = sum(r.get("use_count", 0) for r in rules)
        now = time.time()

        for r in rules:
            rid = r.get("id", 0)
            category = r.get("category", "")
            action = r.get("action", "")
            uses = r.get("use_count", 0)
            success = r.get("success_count", 0)
            last_used = r.get("last_used", 0)
            score = r.get("score", 3.0)

            # Zero-success: used 5+ times but never succeeded
            if uses >= 5 and success == 0:
                zero_success.append({
                    "id": rid, "category": category, "action": action,
                    "uses": uses, "recommendation": "Consider deprioritizing",
                })

            # Over-relied: single rule has >40% of all uses
            if total_uses > 0 and uses / total_uses > 0.4:
                over_relied.append({
                    "id": rid, "category": category,
                    "use_pct": round(uses / total_uses * 100),
                    "recommendation": "Diversify decision-making",
                })

            # Stale: not used in 7+ days
            if last_used > 0 and (now - last_used) > 7 * 86400:
                stale.append({
                    "id": rid, "category": category,
                    "days_unused": round((now - last_used) / 86400),
                })

            # Healthy
            if uses >= 3 and success > 0 and success / max(uses, 1) > 0.3:
                healthy.append({
                    "id": rid, "category": category, "action": action,
                    "success_rate": round(success / uses * 100),
                })

        # Conflicting: same category has both prefer and avoid
        cat_actions: dict[str, set] = {}
        for r in rules:
            cat = r.get("category", "")
            act = r.get("action", "")
            cat_actions.setdefault(cat, set()).add(act)
        for cat, actions in cat_actions.items():
            if "prefer" in actions and "avoid" in actions:
                conflicting.append({
                    "category": cat,
                    "recommendation": "Review rules — both prefer and avoid exist",
                })

        report = {
            "total_rules": len(rules),
            "healthy": len(healthy),
            "zero_success": zero_success,
            "over_relied": over_relied,
            "stale": stale,
            "conflicting": conflicting,
            "health_score": round(len(healthy) / max(len(rules), 1) * 100),
            "recommendations": self._generate_recommendations(
                zero_success, over_relied, conflicting),
        }

        # Auto-deprioritize zero-success rules (lower their score)
        if zero_success:
            try:
                from core.memory.unified_memory import get_unified_memory
                mi = get_unified_memory().get_memory_intelligence()
                for zs in zero_success:
                    rid = zs.get("id", 0)
                    if rid:
                        mi.update_score(rid, 2.0, "zero_success_deprioritized")
            except Exception as exc:
                logger.debug("zero-success deprioritisation failed: %s", exc)

        self._last_check = report
        return report

    @staticmethod
    def _generate_recommendations(zero_success, over_relied, conflicting):
        recs = []
        if zero_success:
            recs.append("{} rules never succeed — deprioritize them".format(len(zero_success)))
        if over_relied:
            recs.append("Decision-making over-relies on {} rule(s)".format(len(over_relied)))
        if conflicting:
            recs.append("{} categories have conflicting prefer+avoid rules".format(len(conflicting)))
        if not recs:
            recs.append("All rules healthy")
        return recs

    def get_last_check(self) -> dict[str, Any]:
        return self._last_check


_instance: RuleHealthChecker | None = None
_instance_lock = _threading.Lock()

def get_rule_health_checker() -> RuleHealthChecker:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RuleHealthChecker()
    return _instance
