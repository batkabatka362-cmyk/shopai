"""ActionCoordinator — prevents conflicting actions and manages execution.

Problems this solves:
  - Two loops both trying to change the same product's price
  - Ad campaign launched while budget is depleted
  - Email sent to customer who just purchased
  - Inventory reorder placed twice
  - Price raised on a product that's already losing customers

Uses cooldowns, conflict detection, and risk assessment to gate actions.
"""
from __future__ import annotations

import time
import threading
from typing import Any

from utils.logger import get_logger
from utils.helpers import generate_id

logger = get_logger("orchestrator.action_coordinator")


# Risk levels for different action types
ACTION_RISK = {
    "price_increase": "high",
    "price_decrease": "medium",
    "ad_launch": "medium",
    "ad_pause": "low",
    "ad_budget_increase": "medium",
    "ad_budget_decrease": "low",
    "inventory_reorder": "medium",
    "email_campaign": "medium",
    "product_create": "medium",
    "product_update": "low",
    "listing_disable": "high",
    "discount_create": "medium",
    "content_publish": "low",
}

# Conflict rules: action pairs that cannot happen simultaneously
CONFLICT_RULES = [
    # Can't raise AND lower price on same product
    {"action_a": "price_increase", "action_b": "price_decrease", "scope": "product_id"},
    # Can't launch AND pause same campaign
    {"action_a": "ad_launch", "action_b": "ad_pause", "scope": "campaign_id"},
    # Can't increase AND decrease same campaign budget
    {"action_a": "ad_budget_increase", "action_b": "ad_budget_decrease", "scope": "campaign_id"},
    # Can't disable a product AND create a discount for it
    {"action_a": "listing_disable", "action_b": "discount_create", "scope": "product_id"},
    # Can't reorder inventory if already reordered recently
    {"action_a": "inventory_reorder", "action_b": "inventory_reorder", "scope": "product_id"},
]

# Cooldowns per action type (seconds)
ACTION_COOLDOWNS = {
    "price_increase": 43200,       # 12 hours
    "price_decrease": 43200,       # 12 hours
    "ad_launch": 3600,             # 1 hour
    "ad_pause": 1800,              # 30 minutes
    "ad_budget_increase": 21600,   # 6 hours
    "ad_budget_decrease": 21600,   # 6 hours
    "inventory_reorder": 604800,   # 7 days
    "email_campaign": 86400,       # 24 hours per target
    "product_create": 300,         # 5 minutes
    "listing_disable": 3600,       # 1 hour
    "discount_create": 3600,       # 1 hour
}


class ActionCoordinator:
    """Gates and coordinates actions to prevent conflicts.

    Usage:
        coordinator = ActionCoordinator()

        # Before executing an action:
        verdict = coordinator.check(action_type="price_increase", target_id="prod_123")
        if verdict["allowed"]:
            # execute the action
            coordinator.record(action_type="price_increase", target_id="prod_123", result="success")
        else:
            # skip or queue
            print(verdict["reason"])
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ledger: list[dict[str, Any]] = []  # All recorded actions
        self._in_flight: dict[str, dict[str, Any]] = {}  # Currently executing

    def check(
        self,
        action_type: str,
        target_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check if an action is allowed right now.

        Returns:
            {"allowed": True/False, "reason": str, "risk": str, "conflicts": [...]}

        NOTE: this is a read-only inspection. Two threads can both
        pass `check()` before either calls `start_action()` —
        callers that need atomic check-and-start should use
        `try_start()` instead.
        """
        with self._lock:
            return self._check_unlocked(action_type, target_id, context)

    def _check_unlocked(
        self,
        action_type: str,
        target_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Inner implementation of `check()` that assumes the
        caller already holds `self._lock`. Extracted so `try_start`
        can run check + reservation under a single lock acquire."""
        risk = ACTION_RISK.get(action_type, "low")
        conflicts: list[dict[str, Any]] = []
        reasons: list[str] = []

        # Check cooldowns
        cooldown = ACTION_COOLDOWNS.get(action_type, 0)
        if cooldown > 0:
            last = self._find_last_action(action_type, target_id)
            if last:
                elapsed = time.time() - last["timestamp"]
                if elapsed < cooldown:
                    remaining = int(cooldown - elapsed)
                    reasons.append(f"Cooldown active: {remaining}s remaining")
                    conflicts.append({
                        "type": "cooldown",
                        "action": action_type,
                        "target": target_id,
                        "remaining_seconds": remaining,
                    })

        # Check conflict rules
        for rule in CONFLICT_RULES:
            if action_type in (rule["action_a"], rule["action_b"]):
                conflicting_type = (
                    rule["action_b"] if action_type == rule["action_a"]
                    else rule["action_a"]
                )
                scope_key = rule["scope"]
                # Check if conflicting action is in-flight or recently executed
                conflict = self._find_conflict(
                    conflicting_type, target_id, scope_key
                )
                if conflict:
                    reasons.append(
                        f"Conflicts with {conflicting_type} on {scope_key}={target_id}"
                    )
                    conflicts.append({
                        "type": "conflict",
                        "action": conflicting_type,
                        "target": target_id,
                        "rule": rule,
                    })

        # Check in-flight duplicates
        flight_key = f"{action_type}:{target_id}"
        if flight_key in self._in_flight:
            reasons.append("Same action already in-flight")
            conflicts.append({"type": "in_flight", "action": action_type, "target": target_id})

        allowed = len(conflicts) == 0
        if not allowed:
            logger.warning(
                "Action BLOCKED: %s on %s — %s",
                action_type, target_id, "; ".join(reasons),
            )

        return {
            "allowed": allowed,
            "reason": "; ".join(reasons) if reasons else "OK",
            "risk": risk,
            "conflicts": conflicts,
        }

    def record(
        self,
        action_type: str,
        target_id: str = "",
        result: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a completed action in the ledger."""
        with self._lock:
            action_id = generate_id("action")
            entry = {
                "action_id": action_id,
                "action_type": action_type,
                "target_id": target_id,
                "result": result,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }
            self._ledger.append(entry)

            # Remove from in-flight
            flight_key = f"{action_type}:{target_id}"
            self._in_flight.pop(flight_key, None)

            # Keep ledger bounded
            if len(self._ledger) > 5000:
                self._ledger = self._ledger[-5000:]

            return action_id

    def start_action(self, action_type: str, target_id: str = "") -> str | None:
        """Mark an action as in-flight (about to execute).

        Returns the new action_id, or None if an action of the same
        type + target is already in-flight. Previously this method
        unconditionally overwrote any existing in_flight entry, so
        two concurrent starters silently shared the same flight_key
        and the first finish_action removed BOTH entries' tracking.
        Refusing the second start makes the in-flight bookkeeping
        actually authoritative.
        """
        with self._lock:
            flight_key = f"{action_type}:{target_id}"
            if flight_key in self._in_flight:
                logger.warning(
                    "ActionCoordinator: start_action refused — %s already in-flight",
                    flight_key,
                )
                return None
            action_id = generate_id("action")
            self._in_flight[flight_key] = {
                "action_id": action_id,
                "action_type": action_type,
                "target_id": target_id,
                "started_at": time.time(),
            }
            return action_id

    def try_start(
        self,
        action_type: str,
        target_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically check + start an action under a single lock
        acquire. Returns the same shape as `check()` plus an
        ``action_id`` field on success.

        The previous `check()` then `start_action()` pattern had a
        TOCTOU race window: two threads could both pass `check()`
        before either called `start_action()`, then both proceed
        with the same target. This atomic variant closes the gap
        for callers that need it.
        """
        with self._lock:
            verdict = self._check_unlocked(action_type, target_id, context)
            if not verdict["allowed"]:
                return verdict
            flight_key = f"{action_type}:{target_id}"
            action_id = generate_id("action")
            self._in_flight[flight_key] = {
                "action_id": action_id,
                "action_type": action_type,
                "target_id": target_id,
                "started_at": time.time(),
            }
            verdict["action_id"] = action_id
            return verdict

    def finish_action(
        self,
        action_type: str,
        target_id: str = "",
        result: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Mark an in-flight action as completed."""
        return self.record(action_type, target_id, result, metadata)

    def get_in_flight(self) -> list[dict[str, Any]]:
        """Get all currently in-flight actions."""
        with self._lock:
            return list(self._in_flight.values())

    def get_recent_actions(self, limit: int = 20, action_type: str | None = None) -> list[dict[str, Any]]:
        """Get recent actions from the ledger."""
        with self._lock:
            actions = self._ledger
            if action_type:
                actions = [a for a in actions if a.get("action_type") == action_type]
            # Defensive copy so caller mutation can't poison the
            # ledger entries.
            return [dict(a) for a in actions[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get action coordinator statistics."""
        with self._lock:
            total = len(self._ledger)
            by_type: dict[str, int] = {}
            by_result: dict[str, int] = {}
            for a in self._ledger:
                # Use .get so a malformed ledger entry (missing
                # action_type or result) doesn't crash the whole
                # stats call with KeyError.
                at = a.get("action_type") or "unknown"
                rs = a.get("result") or "unknown"
                by_type[at] = by_type.get(at, 0) + 1
                by_result[rs] = by_result.get(rs, 0) + 1
            return {
                "total_actions": total,
                "in_flight": len(self._in_flight),
                "by_type": by_type,
                "by_result": by_result,
            }

    def _find_last_action(self, action_type: str, target_id: str) -> dict[str, Any] | None:
        """Find the most recent matching action in the ledger."""
        for entry in reversed(self._ledger):
            if entry.get("action_type") == action_type:
                if not target_id or entry.get("target_id") == target_id:
                    return entry
        return None

    def _find_conflict(self, action_type: str, target_id: str, scope_key: str) -> dict[str, Any] | None:
        """Find a conflicting action that's in-flight or within cooldown."""
        # Check in-flight
        for flight in self._in_flight.values():
            if flight.get("action_type") == action_type and flight.get("target_id") == target_id:
                return flight

        # Check recent ledger (within cooldown period)
        cooldown = ACTION_COOLDOWNS.get(action_type, 3600)
        cutoff = time.time() - cooldown
        for entry in reversed(self._ledger):
            if entry.get("timestamp", 0) < cutoff:
                break
            if entry.get("action_type") == action_type and entry.get("target_id") == target_id:
                return entry

        return None
