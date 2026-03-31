"""Smart Scheduling — execute the right action at the right time.

Features:
  - Time-based action scheduling (price updates morning, emails afternoon)
  - Cooldown enforcement (don't email same customer within 24h)
  - Seasonal awareness (Black Friday, Christmas prep)
  - Action deduplication (don't run same action twice)
  - Priority queue with dependency resolution
"""
from __future__ import annotations

import time
import threading
from typing import Any, Callable

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("scheduling")


# Optimal timing for different action types (24h clock)
ACTION_TIMING = {
    "pricing_update": {"best_hours": (6, 10), "reason": "Before peak shopping hours"},
    "email_campaign": {"best_hours": (10, 14), "reason": "Highest open rates"},
    "ad_launch": {"best_hours": (16, 21), "reason": "Evening browsing peak"},
    "content_publish": {"best_hours": (8, 12), "reason": "Morning content consumption"},
    "inventory_reorder": {"best_hours": (7, 9), "reason": "Business hours start"},
    "seo_update": {"best_hours": (2, 6), "reason": "Low traffic window for changes"},
    "report_generation": {"best_hours": (6, 8), "reason": "Ready for morning review"},
}

# Known seasonal events
SEASONAL_EVENTS = {
    "black_friday": {"month": 11, "day_range": (22, 29), "prep_days": 14,
                     "actions": ["increase_inventory", "prepare_discounts", "boost_ad_spend"]},
    "cyber_monday": {"month": 12, "day_range": (1, 3), "prep_days": 7,
                     "actions": ["launch_promotions", "email_blast"]},
    "christmas": {"month": 12, "day_range": (20, 25), "prep_days": 21,
                  "actions": ["gift_guides", "shipping_cutoff_alert", "holiday_pricing"]},
    "new_year": {"month": 1, "day_range": (1, 5), "prep_days": 7,
                 "actions": ["clearance_sale", "new_year_campaign"]},
    "valentines": {"month": 2, "day_range": (10, 14), "prep_days": 14,
                   "actions": ["gift_collection", "couples_deals"]},
    "back_to_school": {"month": 8, "day_range": (15, 31), "prep_days": 14,
                       "actions": ["student_discounts", "bundle_deals"]},
}

# Cooldown durations per action type (seconds)
ACTION_COOLDOWNS = {
    "email_to_customer": 86400,     # 24h per customer
    "price_change": 43200,          # 12h per product
    "ad_budget_change": 21600,      # 6h per campaign
    "inventory_reorder": 604800,    # 7 days per product
    "content_publish": 3600,        # 1h
    "seo_update": 86400,            # 24h
}


class SmartScheduler:
    """Intelligent action scheduler with timing, cooldowns, and seasonal awareness."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduled: list[dict[str, Any]] = []
        self._executed: list[dict[str, Any]] = []
        self._cooldowns: dict[str, float] = {}  # action_key → last_executed_time
        self._running_actions: set[str] = set()  # Currently executing action IDs

    def schedule(self, action_type: str, data: dict[str, Any],
                 target_id: str = "", priority: int = 5) -> dict[str, Any]:
        """Schedule an action with smart timing.

        Returns scheduling decision with timing recommendation.
        """
        action_id = generate_id("sched")
        now = time.time()
        current_hour = time.localtime(now).tm_hour

        # Check cooldown
        cooldown_key = f"{action_type}:{target_id}" if target_id else action_type
        if self._is_cooled_down(cooldown_key, action_type):
            remaining = self._cooldown_remaining(cooldown_key, action_type)
            return {
                "action_id": action_id,
                "status": "cooled_down",
                "action_type": action_type,
                "cooldown_remaining_seconds": round(remaining),
                "reason": f"Cooldown active — retry in {remaining/60:.0f} min",
            }

        # Check dedup
        if self._is_duplicate(action_type, target_id, data):
            return {
                "action_id": action_id,
                "status": "duplicate",
                "action_type": action_type,
                "reason": "Same action already scheduled",
            }

        # Determine optimal timing
        timing = ACTION_TIMING.get(action_type, {})
        best_start, best_end = timing.get("best_hours", (0, 24))
        timing_reason = timing.get("reason", "No timing preference")

        if best_start <= current_hour <= best_end:
            execute_now = True
            timing_note = f"Optimal time ({timing_reason})"
        elif priority <= 2:
            execute_now = True
            timing_note = f"High priority override (best: {best_start}:00-{best_end}:00)"
        else:
            execute_now = False
            timing_note = f"Queued — best time {best_start}:00-{best_end}:00 ({timing_reason})"

        # Check seasonal context
        seasonal = self._check_seasonal()

        entry = {
            "action_id": action_id,
            "action_type": action_type,
            "target_id": target_id,
            "data": data,
            "priority": priority,
            "status": "ready" if execute_now else "scheduled",
            "timing": timing_note,
            "seasonal_context": seasonal,
            "scheduled_at": now,
        }

        with self._lock:
            self._scheduled.append(entry)
            if len(self._scheduled) > 5000:
                self._scheduled = self._scheduled[-5000:]

        return entry

    def execute_ready(self, executor: Callable | None = None) -> list[dict[str, Any]]:
        """Execute all ready actions. Returns results."""
        results = []

        with self._lock:
            ready = [a for a in self._scheduled if a["status"] == "ready"]

        # Sort by priority (lower = more urgent)
        ready.sort(key=lambda a: a["priority"])

        for action in ready:
            action_id = action["action_id"]
            action_type = action["action_type"]
            target_id = action.get("target_id", "")

            # Execute
            action["status"] = "executing"
            try:
                if executor:
                    result = executor(action)
                else:
                    result = {"status": "executed", "action": action_type}

                action["status"] = "executed"
                action["executed_at"] = time.time()

                # Record cooldown
                cooldown_key = f"{action_type}:{target_id}" if target_id else action_type
                self._cooldowns[cooldown_key] = time.time()

                results.append({"action_id": action_id, "status": "executed", "result": result})

            except Exception as exc:
                action["status"] = "failed"
                action["error"] = str(exc)
                results.append({"action_id": action_id, "status": "failed", "error": str(exc)})

        with self._lock:
            self._executed.extend(results)
            if len(self._executed) > 2000:
                self._executed = self._executed[-2000:]

        return results

    def get_seasonal_context(self) -> dict[str, Any]:
        """Get current seasonal context and upcoming events."""
        return self._check_seasonal()

    def _check_seasonal(self) -> dict[str, Any]:
        """Check if any seasonal events are upcoming."""
        now = time.localtime()
        month = now.tm_mon
        day = now.tm_mday

        upcoming = []
        active = []

        for event_name, config in SEASONAL_EVENTS.items():
            event_month = config["month"]
            day_start, day_end = config["day_range"]
            prep_days = config["prep_days"]

            # Check if event is active
            if month == event_month and day_start <= day <= day_end:
                active.append({
                    "event": event_name,
                    "status": "active",
                    "actions": config["actions"],
                })

            # Check if we should be preparing
            elif (month == event_month and day < day_start and day_start - day <= prep_days) or \
                 (month == event_month - 1 and (30 - day + day_start) <= prep_days):
                days_until = day_start - day if month == event_month else 30 - day + day_start
                upcoming.append({
                    "event": event_name,
                    "days_until": max(0, days_until),
                    "prep_actions": config["actions"],
                    "status": "prep_time",
                })

        return {
            "active_events": active,
            "upcoming_events": upcoming,
            "is_peak_season": len(active) > 0,
            "should_prepare": len(upcoming) > 0,
        }

    def _is_cooled_down(self, key: str, action_type: str) -> bool:
        cooldown = ACTION_COOLDOWNS.get(action_type, 300)
        last = self._cooldowns.get(key, 0)
        return (time.time() - last) < cooldown

    def _cooldown_remaining(self, key: str, action_type: str) -> float:
        cooldown = ACTION_COOLDOWNS.get(action_type, 300)
        last = self._cooldowns.get(key, 0)
        return max(0, cooldown - (time.time() - last))

    def _is_duplicate(self, action_type: str, target_id: str, data: dict) -> bool:
        """Check if same action is already scheduled and pending."""
        with self._lock:
            for a in self._scheduled:
                if (a["status"] in ("ready", "scheduled") and
                        a["action_type"] == action_type and
                        a.get("target_id") == target_id):
                    return True
        return False

    def get_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if status:
                return [a for a in self._scheduled if a["status"] == status]
            return list(self._scheduled)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            statuses = {}
            for a in self._scheduled:
                s = a["status"]
                statuses[s] = statuses.get(s, 0) + 1
            return {
                "total_scheduled": len(self._scheduled),
                "total_executed": len(self._executed),
                "by_status": statuses,
                "active_cooldowns": len([k for k, v in self._cooldowns.items()
                                         if time.time() - v < 86400]),
            }
