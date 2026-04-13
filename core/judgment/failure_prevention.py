"""FailureContextPrevention — prevents repeating mistakes in similar conditions.

Examines current context against past failure episodes.
If conditions match too closely → AUTO VETO.

"System 'raise price' гэж хэлнэ. FailureContextPrevention:
 Сүүлийн 2 price increase: (1) competitor_active=true + inventory<100 → fail.
 Одоо competitor_active=true + inventory=85. Match: 82%. VETO."
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("judgment.failure_prevention")

# Veto thresholds
VETO_THRESHOLD = 0.70      # >70% match → auto veto
WARNING_THRESHOLD = 0.40   # 40-70% → warning
TIME_DECAY_DAYS = 180      # Failures older than 180 days weighted 50% less

# Context factors and their weights for matching
CONTEXT_FACTORS = {
    "health_grade": 0.20,
    "churn_pct": 0.15,
    "stockout_risk": 0.15,
    "confidence_score": 0.15,
    "net_margin": 0.15,
    "critical_alerts": 0.10,
    "competitor_active": 0.10,
}


class FailureContextPrevention:
    """Prevents repeating mistakes by matching current conditions to past failures.

    Usage:
        prevention = FailureContextPrevention(episodic_memory)
        result = prevention.check("pricing", current_context)
        if result["vetoed"]:
            print(f"VETO: {result['reason']}")
    """

    def __init__(self, episodic_memory: Any = None) -> None:
        self._memory = episodic_memory

    def check(
        self,
        decision_type: str,
        current_context: dict[str, Any],
        action: str = "",
    ) -> dict[str, Any]:
        """Check if current decision matches past failure conditions.

        Returns:
            {
                "vetoed": bool,
                "warning": bool,
                "match_score": float (0-1),
                "matching_failures": [...],
                "reason": str,
                "recommendation": str,
            }
        """
        if self._memory is None:
            return {"vetoed": False, "warning": False, "match_score": 0, "matching_failures": [], "reason": "No episodic memory", "recommendation": "proceed"}

        # Get past failures for this decision type
        failures = self._memory.get_failures(decision_type=decision_type, max_age_days=TIME_DECAY_DAYS * 2)
        if not failures:
            return {"vetoed": False, "warning": False, "match_score": 0, "matching_failures": [], "reason": "No past failures", "recommendation": "proceed"}

        # Compare current context to each failure
        matches = []
        for failure in failures:
            failure_context = failure.get("context", {})
            score = self._match_score(current_context, failure_context)

            # Apply time decay
            age_days = (time.time() - failure.get("timestamp", 0)) / 86400
            decay = 0.5 if age_days > TIME_DECAY_DAYS else 1.0
            weighted_score = score * decay

            if weighted_score >= WARNING_THRESHOLD:
                matches.append({
                    "episode_id": failure.get("episode_id", "?"),
                    "action": failure.get("action", "?"),
                    "match_score": round(weighted_score, 3),
                    "age_days": round(age_days),
                    "lesson": failure.get("lesson", ""),
                    "original_context": failure_context,
                })

        if not matches:
            return {"vetoed": False, "warning": False, "match_score": 0, "matching_failures": [], "reason": "No matching failures", "recommendation": "proceed"}

        # Sort by match score
        matches.sort(key=lambda m: m["match_score"], reverse=True)
        best_match = matches[0]["match_score"]

        vetoed = best_match >= VETO_THRESHOLD
        warning = not vetoed and best_match >= WARNING_THRESHOLD

        if vetoed:
            reason = (
                f"VETO: Current conditions match past failure with {best_match:.0%} similarity. "
                f"Past failure: {matches[0]['action']} ({matches[0]['age_days']} days ago). "
                f"Lesson: {matches[0]['lesson']}"
            )
            recommendation = "delay"
        elif warning:
            reason = (
                f"WARNING: Conditions partially match past failure ({best_match:.0%}). "
                f"Past failure: {matches[0]['action']}. Consider human review."
            )
            recommendation = "review"
        else:
            reason = "No significant match to past failures"
            recommendation = "proceed"

        logger.info(
            "Failure check for %s/%s: score=%.2f, vetoed=%s, matches=%d",
            decision_type, action, best_match, vetoed, len(matches),
        )

        return {
            "vetoed": vetoed,
            "warning": warning,
            "match_score": round(best_match, 3),
            "matching_failures": matches[:5],
            "reason": reason,
            "recommendation": recommendation,
        }

    def _match_score(self, current: dict[str, Any], failure: dict[str, Any]) -> float:
        """Calculate how closely current context matches a failure context."""
        total_weight = 0
        score = 0

        for factor, weight in CONTEXT_FACTORS.items():
            c_val = current.get(factor)
            f_val = failure.get(factor)

            if c_val is None or f_val is None:
                continue
            # Don't blend bool with numeric — bool is a subclass of
            # int in Python, so without this guard `isinstance(True,
            # (int, float))` is True and the numeric branch below
            # would silently mishandle a True/0 comparison.
            if isinstance(c_val, bool) != isinstance(f_val, bool):
                continue

            total_weight += weight

            if isinstance(c_val, bool) and isinstance(f_val, bool):
                if c_val == f_val:
                    score += weight
            elif isinstance(c_val, str) and isinstance(f_val, str):
                if c_val == f_val:
                    score += weight
            elif isinstance(c_val, (int, float)) and isinstance(f_val, (int, float)):
                # Compute UNIT-FREE relative similarity. The previous
                # `max(abs(c_val), abs(f_val), 1)` form hard-coded a
                # floor of 1, which silently inflated the similarity
                # of small fractional values: churn_pct=0.05 vs 0.10
                # came out at 95% similar even though they differ by
                # 2x. Now we drop the floor and handle the both-zero
                # case explicitly so any sub-1 values still produce
                # the right relative ratio.
                both = max(abs(c_val), abs(f_val))
                if both == 0:
                    similarity = 1.0
                else:
                    diff = abs(c_val - f_val) / both
                    similarity = max(0.0, 1.0 - diff)
                score += weight * similarity

        return score / max(total_weight, 0.01)
