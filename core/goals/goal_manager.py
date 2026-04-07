"""GoalManager — dynamically selects the best goal based on current store conditions.

Instead of passing a static goal="maximize_profit", GoalManager examines
financial health, inventory, customer churn, and seasonal context to
automatically pick the right goal.

Goals:
  - maximize_profit: margins healthy, no urgent issues
  - grow_customers: churn risk high, need retention
  - increase_aov: customer base stable, revenue per order low
  - survive_crisis: cash flow negative, margins critical
  - capture_opportunity: seasonal peak approaching, trending product

Hysteresis: won't switch goals for 5 cycles minimum to prevent thrashing.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.helpers import safe_float, safe_int
from utils.logger import get_logger

logger = get_logger("goals.manager")


def _section(situation: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a situation section as a real dict.

    Replaces `situation.get(name, {})` which returned the literal
    default ONLY when the key was missing. If the key was present
    with a None value (initial state or post-partial-update),
    `.get` returned None and the next chained `.get(...)` crashed
    with AttributeError. Same defensive pattern from PriorityEngine
    audit pass 21.
    """
    val = situation.get(name) if isinstance(situation, dict) else None
    return val if isinstance(val, dict) else {}

# Goal definitions with trigger conditions and priorities
GOAL_DEFINITIONS = {
    "survive_crisis": {
        "priority": 1,  # Highest priority — existential threat
        "description": "Cash flow or margins critical — focus on survival",
        "triggers": {
            "health_grade_in": ("D", "F"),
            "critical_alerts_gt": 0,
        },
    },
    "grow_customers": {
        "priority": 2,
        "description": "Customer churn risk high — focus on retention and acquisition",
        "triggers": {
            "churn_risk_pct_gt": 40,
        },
    },
    "capture_opportunity": {
        "priority": 3,
        "description": "Seasonal peak or trending product — capture the moment",
        "triggers": {
            "seasonal_opportunity": True,
        },
    },
    "increase_aov": {
        "priority": 4,
        "description": "Customer base stable — focus on revenue per order",
        "triggers": {
            "aov_below_median": True,
        },
    },
    "maximize_profit": {
        "priority": 5,  # Default — everything is fine
        "description": "Normal operation — optimize for profit",
        "triggers": {},  # Default when nothing else triggers
    },
}

# Seasonal peaks (month, day_start, day_end, prep_days_before)
SEASONAL_PEAKS = [
    (11, 22, 29, 14),   # Black Friday
    (12, 1, 3, 7),      # Cyber Monday
    (12, 15, 25, 21),   # Christmas
    (2, 10, 14, 14),    # Valentine's
    (8, 15, 31, 14),    # Back to school
]

HYSTERESIS_CYCLES = 5  # Don't switch for at least 5 cycles


class GoalManager:
    """Dynamically selects and manages business goals.

    Usage:
        manager = GoalManager()
        result = manager.select_goal(snapshot.get_situation())
        # result = {"goal": "grow_customers", "reason": "...", "confidence": 0.85}
    """

    # Bound on the in-memory switch history. The previous version
    # let it grow forever — over a long-running daemon this is a
    # slow memory leak. get_switch_history already only returned
    # the last 20, so the cap can be just slightly larger.
    _MAX_SWITCH_HISTORY = 200

    def __init__(self) -> None:
        self._current_goal = "maximize_profit"
        self._goal_since_cycle = 0
        self._cycle_count = 0
        self._switch_history: list[dict[str, Any]] = []
        # Lock guarding the mutable state above. Multiple cycles
        # plus dashboard reads previously raced on _current_goal
        # and _switch_history mutations.
        self._lock = threading.Lock()

    def select_goal(self, situation: dict[str, Any], cycle_number: int = 0) -> dict[str, Any]:
        """Select the best goal based on current store situation.

        Args:
            situation: From StoreSnapshot.get_situation()
            cycle_number: Current cycle count (for hysteresis)

        Returns:
            {"goal": str, "reason": str, "switched": bool, "confidence": float}
        """
        # Coerce situation defensively so the rest of the method
        # can rely on dict semantics.
        if not isinstance(situation, dict):
            situation = {}

        with self._lock:
            self._cycle_count = cycle_number
            recommended = self._evaluate_goals(situation)

            # Hysteresis: don't switch if we recently switched
            cycles_on_current = cycle_number - self._goal_since_cycle
            switched = False

            if recommended["goal"] != self._current_goal:
                if cycles_on_current >= HYSTERESIS_CYCLES or recommended["priority"] <= 2:
                    # Switch: either enough cycles passed, or it's urgent (priority 1-2)
                    old_goal = self._current_goal
                    self._current_goal = recommended["goal"]
                    self._goal_since_cycle = cycle_number
                    switched = True
                    self._switch_history.append({
                        "from": old_goal,
                        "to": recommended["goal"],
                        "reason": recommended["reason"],
                        "cycle": cycle_number,
                        "timestamp": time.time(),
                    })
                    # Trim to bound — prevents the slow memory leak
                    # in long-running daemons.
                    if len(self._switch_history) > self._MAX_SWITCH_HISTORY:
                        self._switch_history = self._switch_history[-self._MAX_SWITCH_HISTORY:]
                    logger.info(
                        "Goal switched: %s → %s (reason: %s)",
                        old_goal, recommended["goal"], recommended["reason"],
                    )
                else:
                    # Hysteresis: keep current goal
                    recommended["note"] = (
                        f"Would switch to {recommended['goal']} but hysteresis "
                        f"({cycles_on_current}/{HYSTERESIS_CYCLES} cycles)"
                    )
                    recommended["goal"] = self._current_goal
                    recommended["reason"] = f"Staying with {self._current_goal} (hysteresis)"

            return {
                "goal": recommended["goal"],
                "reason": recommended["reason"],
                "switched": switched,
                "confidence": recommended.get("confidence", 0.8),
                "priority": recommended.get("priority", 5),
                "alternatives": recommended.get("alternatives", []),
                "cycles_on_current_goal": cycles_on_current,
            }

    def should_switch(self, current_goal: str, situation: dict[str, Any]) -> dict[str, Any]:
        """Check if a goal switch is warranted without actually switching."""
        if not isinstance(situation, dict):
            situation = {}
        recommended = self._evaluate_goals(situation)
        return {
            "should_switch": recommended["goal"] != current_goal,
            "recommended_goal": recommended["goal"],
            "reason": recommended["reason"],
            "current_goal": current_goal,
        }

    def get_current_goal(self) -> str:
        with self._lock:
            return self._current_goal

    def get_switch_history(self) -> list[dict[str, Any]]:
        with self._lock:
            # Return defensive copies so caller mutation can't
            # poison the in-memory history.
            return [dict(e) for e in self._switch_history[-20:]]

    def _evaluate_goals(self, situation: dict[str, Any]) -> dict[str, Any]:
        """Evaluate all goals and pick the best one."""
        financial = _section(situation, "financial")
        # inventory currently unused but kept for future rules
        _ = _section(situation, "inventory")
        customers = _section(situation, "customers")
        health = _section(situation, "health")

        candidates = []

        # Check survive_crisis. health_grade falls back through
        # financial → health → "B"; the chain is hand-coded
        # because dict.get(k, default) only fires the default when
        # the key is MISSING (not when present-but-None).
        health_grade = financial.get("health_grade")
        if health_grade is None:
            health_grade = health.get("overall_grade") or "B"
        # safe_int so a None / string critical_alerts can't crash
        # `> 0` with TypeError.
        critical_alerts = safe_int(financial.get("critical_alerts"))
        if health_grade in ("D", "F") or critical_alerts > 0:
            candidates.append({
                "goal": "survive_crisis",
                "priority": 1,
                "confidence": 0.95,
                "reason": f"Financial health grade {health_grade}, {critical_alerts} critical alerts",
            })

        # Check grow_customers. safe_float so None / string churn
        # can't crash the comparison.
        churn_pct = safe_float(customers.get("churn_risk_pct"))
        if churn_pct > 40:
            candidates.append({
                "goal": "grow_customers",
                "priority": 2,
                "confidence": 0.85,
                "reason": f"Customer churn risk at {churn_pct}% — retention needed",
            })

        # Check capture_opportunity (seasonal)
        if self._is_seasonal_opportunity():
            candidates.append({
                "goal": "capture_opportunity",
                "priority": 3,
                "confidence": 0.80,
                "reason": "Seasonal sales peak approaching — prepare inventory and marketing",
            })

        # Check increase_aov
        aov = safe_float(financial.get("aov"))
        if aov > 0 and aov < 40:  # Low AOV threshold
            candidates.append({
                "goal": "increase_aov",
                "priority": 4,
                "confidence": 0.70,
                "reason": f"AOV at ${aov:.2f} — below optimal, cross-sell opportunity",
            })

        # Default: maximize_profit
        candidates.append({
            "goal": "maximize_profit",
            "priority": 5,
            "confidence": 0.75,
            "reason": "Normal operation — optimizing for profit",
        })

        # Sort by priority (lowest number = highest priority)
        candidates.sort(key=lambda c: c["priority"])
        best = candidates[0]
        best["alternatives"] = [
            {"goal": c["goal"], "reason": c["reason"]}
            for c in candidates[1:3]
        ]

        return best

    def _is_seasonal_opportunity(self) -> bool:
        """Check if a seasonal peak is approaching.

        Uses UTC instead of `time.localtime()` so a distributed
        ShopAI deployment fires the same seasonal logic at the
        same wall-clock moment regardless of which timezone the
        server is in. Previously the answer depended on TZ.
        """
        now = time.gmtime()
        month, day = now.tm_mon, now.tm_mday

        for peak_month, day_start, day_end, prep_days in SEASONAL_PEAKS:
            # Check if we're in prep window
            if month == peak_month and day_start - prep_days <= day <= day_end:
                return True
            # Handle cross-month prep (e.g., November prep for Black Friday).
            # Guard against peak_month=1 producing month=0.
            if peak_month > 1 and month == peak_month - 1 and day >= 28 - prep_days:
                return True

        return False
