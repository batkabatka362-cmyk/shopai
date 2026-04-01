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

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("goals.manager")

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

    def __init__(self) -> None:
        self._current_goal = "maximize_profit"
        self._goal_since_cycle = 0
        self._cycle_count = 0
        self._switch_history: list[dict[str, Any]] = []

    def select_goal(self, situation: dict[str, Any], cycle_number: int = 0) -> dict[str, Any]:
        """Select the best goal based on current store situation.

        Args:
            situation: From StoreSnapshot.get_situation()
            cycle_number: Current cycle count (for hysteresis)

        Returns:
            {"goal": str, "reason": str, "switched": bool, "confidence": float}
        """
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
        recommended = self._evaluate_goals(situation)
        return {
            "should_switch": recommended["goal"] != current_goal,
            "recommended_goal": recommended["goal"],
            "reason": recommended["reason"],
            "current_goal": current_goal,
        }

    def get_current_goal(self) -> str:
        return self._current_goal

    def get_switch_history(self) -> list[dict[str, Any]]:
        return self._switch_history[-20:]

    def _evaluate_goals(self, situation: dict[str, Any]) -> dict[str, Any]:
        """Evaluate all goals and pick the best one."""
        financial = situation.get("financial", {})
        inventory = situation.get("inventory", {})
        customers = situation.get("customers", {})
        health = situation.get("health", {})

        candidates = []

        # Check survive_crisis
        health_grade = financial.get("health_grade", health.get("overall_grade", "B"))
        critical_alerts = financial.get("critical_alerts", 0)
        if health_grade in ("D", "F") or critical_alerts > 0:
            candidates.append({
                "goal": "survive_crisis",
                "priority": 1,
                "confidence": 0.95,
                "reason": f"Financial health grade {health_grade}, {critical_alerts} critical alerts",
            })

        # Check grow_customers
        churn_pct = customers.get("churn_risk_pct", 0)
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
        aov = financial.get("aov", 0)
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
        """Check if a seasonal peak is approaching."""
        now = time.localtime()
        month, day = now.tm_mon, now.tm_mday

        for peak_month, day_start, day_end, prep_days in SEASONAL_PEAKS:
            # Check if we're in prep window
            if month == peak_month and day_start - prep_days <= day <= day_end:
                return True
            # Handle cross-month prep (e.g., November prep for Black Friday)
            if month == peak_month - 1 and day >= 28 - prep_days:
                return True

        return False
