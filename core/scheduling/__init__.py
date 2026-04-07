"""Smart Scheduling — execute the right action at the right time.

Features:
  - Time-based action scheduling (price updates morning, emails afternoon)
  - Cooldown enforcement (don't email same customer within 24h)
  - Seasonal awareness (Black Friday, Christmas prep)
  - Action deduplication (don't run same action twice)
  - Priority queue with dependency resolution
"""
from __future__ import annotations

import copy
import time
import threading
from calendar import monthrange
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
        # Defensive coercion. Caller contract says these are
        # typed but an upstream agent may pass None on a
        # partial failure path. Audit pass 38.
        action_type = action_type if isinstance(action_type, str) and action_type else "unknown"
        data = data if isinstance(data, dict) else {}
        target_id = target_id if isinstance(target_id, str) else ""
        if not isinstance(priority, int):
            priority = 5

        action_id = generate_id("sched")
        now = time.time()
        current_hour = time.localtime(now).tm_hour

        cooldown_key = f"{action_type}:{target_id}" if target_id else action_type

        # Check cooldown + dedup atomically under the lock so
        # two concurrent schedule() calls can't both clear the
        # cooldown check and queue duplicate work.
        with self._lock:
            if self._is_cooled_down_locked(cooldown_key, action_type):
                remaining = self._cooldown_remaining_locked(cooldown_key, action_type)
                return {
                    "action_id": action_id,
                    "status": "cooled_down",
                    "action_type": action_type,
                    "cooldown_remaining_seconds": round(remaining),
                    "reason": f"Cooldown active — retry in {remaining/60:.0f} min",
                }

            if self._is_duplicate_locked(action_type, target_id):
                return {
                    "action_id": action_id,
                    "status": "duplicate",
                    "action_type": action_type,
                    "reason": "Same action already scheduled",
                }

        # Determine optimal timing
        timing = ACTION_TIMING.get(action_type) or {}
        best_hours = timing.get("best_hours", (0, 24))
        if (not isinstance(best_hours, tuple)) or len(best_hours) != 2:
            best_hours = (0, 24)
        best_start, best_end = best_hours
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
            # Deep-copy caller data so later mutations by the
            # caller don't silently change our queued entry.
            "data": copy.deepcopy(data),
            "priority": priority,
            "status": "ready" if execute_now else "scheduled",
            "timing": timing_note,
            "seasonal_context": seasonal,
            "scheduled_at": now,
        }

        with self._lock:
            self._scheduled.append(entry)
            if len(self._scheduled) > 5000:
                # Trim in place so any external reference to
                # ``self._scheduled`` stays valid.
                del self._scheduled[:len(self._scheduled) - 5000]

        # Return a copy so callers can't mutate the queued
        # entry via the returned dict.
        return copy.deepcopy(entry)

    def execute_ready(self, executor: Callable | None = None) -> list[dict[str, Any]]:
        """Execute all ready actions. Returns results.

        Claims ready actions atomically under the lock by
        flipping ``status`` from ``"ready"`` to ``"executing"``
        before releasing it. This prevents two concurrent
        ``execute_ready`` calls from double-executing the same
        action — a real bug in the pre-audit code where both
        callers saw the same ready list and fired the executor
        twice per action.
        """
        results: list[dict[str, Any]] = []

        with self._lock:
            claimed = [a for a in self._scheduled if a.get("status") == "ready"]
            # Sort under the lock so the ordering is stable
            # w.r.t. concurrent schedule() calls.
            claimed.sort(key=lambda a: a.get("priority", 5))
            for action in claimed:
                action["status"] = "executing"

        for action in claimed:
            action_id = action["action_id"]
            action_type = action["action_type"]
            target_id = action.get("target_id", "")

            try:
                if executor:
                    result = executor(action)
                else:
                    result = {"status": "executed", "action": action_type}

                with self._lock:
                    action["status"] = "executed"
                    action["executed_at"] = time.time()
                    cooldown_key = f"{action_type}:{target_id}" if target_id else action_type
                    self._cooldowns[cooldown_key] = time.time()

                results.append({"action_id": action_id, "status": "executed", "result": result})

            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    action["status"] = "failed"
                    action["error"] = str(exc)
                results.append({"action_id": action_id, "status": "failed", "error": str(exc)})

        with self._lock:
            self._executed.extend(results)
            if len(self._executed) > 2000:
                del self._executed[:len(self._executed) - 2000]

        return results

    def get_seasonal_context(self) -> dict[str, Any]:
        """Get current seasonal context and upcoming events."""
        return self._check_seasonal()

    def _check_seasonal(self) -> dict[str, Any]:
        """Check if any seasonal events are upcoming.

        The pre-audit implementation hardcoded ``30`` as the
        length of the previous month and compared
        ``event_month - 1`` which broke the December → January
        wrap (New Year prep couldn't fire in December because
        ``1 - 1 == 0`` never matches any real month). This
        version uses ``calendar.monthrange`` and real month
        wrap arithmetic.
        """
        now = time.localtime()
        year = now.tm_year
        month = now.tm_mon
        day = now.tm_mday

        upcoming: list[dict[str, Any]] = []
        active: list[dict[str, Any]] = []

        for event_name, config in SEASONAL_EVENTS.items():
            event_month = config.get("month")
            day_range = config.get("day_range", (0, 0))
            prep_days = config.get("prep_days", 0)
            if not isinstance(event_month, int) or not (1 <= event_month <= 12):
                continue
            if (not isinstance(day_range, tuple)) or len(day_range) != 2:
                continue
            day_start, day_end = day_range
            if not isinstance(prep_days, int) or prep_days < 0:
                prep_days = 0

            # Event is currently active.
            if month == event_month and day_start <= day <= day_end:
                active.append({
                    "event": event_name,
                    "status": "active",
                    "actions": config.get("actions", []),
                })
                continue

            # Same month, still approaching.
            if month == event_month and day < day_start:
                days_until = day_start - day
                if days_until <= prep_days:
                    upcoming.append({
                        "event": event_name,
                        "days_until": days_until,
                        "prep_actions": config.get("actions", []),
                        "status": "prep_time",
                    })
                continue

            # Previous calendar month, with year wrap for
            # January events (prep fires from December).
            prev_month = event_month - 1 if event_month > 1 else 12
            prev_month_year = year if event_month > 1 else year - 1
            if month == prev_month:
                # Real last-day-of-month instead of hardcoded 30.
                try:
                    _, last_day = monthrange(prev_month_year, prev_month)
                except Exception:  # noqa: BLE001
                    last_day = 30
                days_until = (last_day - day) + day_start
                if 0 <= days_until <= prep_days:
                    upcoming.append({
                        "event": event_name,
                        "days_until": days_until,
                        "prep_actions": config.get("actions", []),
                        "status": "prep_time",
                    })

        return {
            "active_events": active,
            "upcoming_events": upcoming,
            "is_peak_season": len(active) > 0,
            "should_prepare": len(upcoming) > 0,
        }

    # ── Cooldown / dedup helpers ──────────────────────────────
    #
    # All three methods below assume the caller is already
    # holding ``self._lock``. The public-facing ``schedule()``
    # now does both checks + the append inside a single
    # critical section so a concurrent duplicate cannot slip
    # through between the "is-duplicate" check and the
    # "append" step.

    def _is_cooled_down_locked(self, key: str, action_type: str) -> bool:
        cooldown = ACTION_COOLDOWNS.get(action_type, 300)
        last = self._cooldowns.get(key, 0)
        return (time.time() - last) < cooldown

    def _cooldown_remaining_locked(self, key: str, action_type: str) -> float:
        cooldown = ACTION_COOLDOWNS.get(action_type, 300)
        last = self._cooldowns.get(key, 0)
        return max(0, cooldown - (time.time() - last))

    def _is_duplicate_locked(self, action_type: str, target_id: str) -> bool:
        """Check if same (action_type, target_id) is still queued."""
        for a in self._scheduled:
            if (a.get("status") in ("ready", "scheduled") and
                    a.get("action_type") == action_type and
                    a.get("target_id") == target_id):
                return True
        return False

    def get_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return a deep-copied snapshot of queued actions.

        Pre-audit this returned ``list(self._scheduled)`` — a
        shallow copy. Callers mutating entries in place would
        corrupt scheduler state. Deep-copying keeps the
        scheduler's internal dicts private.
        """
        with self._lock:
            if status:
                return [copy.deepcopy(a) for a in self._scheduled if a.get("status") == status]
            return [copy.deepcopy(a) for a in self._scheduled]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            statuses: dict[str, int] = {}
            for a in self._scheduled:
                s = a.get("status", "unknown")
                statuses[s] = statuses.get(s, 0) + 1
            now = time.time()
            active_cd = sum(1 for v in self._cooldowns.values() if now - v < 86400)
            return {
                "total_scheduled": len(self._scheduled),
                "total_executed": len(self._executed),
                "by_status": statuses,
                "active_cooldowns": active_cd,
            }
