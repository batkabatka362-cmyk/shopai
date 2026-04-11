"""Time Intelligence — delay handler.

Handles intentional delays: cool-down periods between related tasks,
rate limiting to prevent overload, and scheduled delays for deferred tasks.

Model note: Would use LLaMA for complex timing strategy around delays.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any


_COOLDOWN_SECONDS_BY_DOMAIN: dict[str, float] = {
    "marketing": 30.0,
    "communication": 15.0,
    "inventory": 5.0,
    "orders": 2.0,
    "pricing": 10.0,
    "analytics": 0.0,
    "catalog": 5.0,
    "infrastructure": 0.0,
    "general": 5.0,
}

_RATE_LIMIT_PER_MINUTE_BY_DOMAIN: dict[str, int] = {
    "marketing": 5,
    "communication": 10,
    "inventory": 20,
    "orders": 50,
    "pricing": 15,
    "analytics": 10,
    "catalog": 10,
    "infrastructure": 5,
    "general": 10,
}

_DEFERRED_URGENCY_DELAY_SECONDS = 300.0


def compute_delays(
    classified_tasks: list[dict[str, Any]],
    triggered_tasks: list[dict[str, Any]],
    execution_order: list[str],
    current_time: str,
) -> dict[str, Any]:
    """Compute intentional delays for tasks that need them.

    Args:
        classified_tasks: All classified tasks.
        triggered_tasks: Tasks that have been triggered.
        execution_order: Dependency-sorted task IDs.
        current_time: ISO timestamp of current time.

    Returns:
        Structured dict with delayed tasks and their resume times.
    """
    try:
        classified_tasks = copy.deepcopy(classified_tasks)
        current_dt = _parse_time(current_time)
        triggered_ids = {t["task_id"] for t in triggered_tasks}
        task_map = {t["task_id"]: t for t in classified_tasks}

        delayed: list[dict[str, Any]] = []
        domain_last_trigger: dict[str, datetime] = {}

        for task_id in execution_order:
            task = task_map.get(task_id)
            if not task:
                continue
            if task_id not in triggered_ids:
                continue

            domain = task.get("domain", "general")
            urgency = task.get("urgency", "normal")

            cooldown_delay = _check_cooldown(domain, domain_last_trigger, current_dt)
            rate_delay = _check_rate_limit(domain, domain_last_trigger, current_dt)
            deferred_delay = _check_deferred(urgency)

            total_delay = max(cooldown_delay, rate_delay, deferred_delay)

            if total_delay > 0:
                resume_dt = current_dt + timedelta(seconds=total_delay)
                reason_parts = []
                if cooldown_delay > 0:
                    reason_parts.append(f"cooldown({domain}:{cooldown_delay}s)")
                if rate_delay > 0:
                    reason_parts.append(f"rate_limit({domain}:{rate_delay}s)")
                if deferred_delay > 0:
                    reason_parts.append(f"deferred_urgency({deferred_delay}s)")

                delayed.append({
                    "task_id": task_id,
                    "reason": "; ".join(reason_parts),
                    "delay_seconds": round(total_delay, 2),
                    "resume_at": resume_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

            domain_last_trigger[domain] = current_dt

        return {
            "status": "success",
            "delayed_tasks": delayed,
            "delayed_count": len(delayed),
        }
    except Exception as exc:
        return {
            "status": "error",
            "delayed_tasks": [],
            "delayed_count": 0,
            "error": str(exc),
        }


def _check_cooldown(
    domain: str,
    domain_last_trigger: dict[str, datetime],
    current_dt: datetime,
) -> float:
    """Check if a cooldown period is needed for this domain."""
    cooldown = _COOLDOWN_SECONDS_BY_DOMAIN.get(domain, 5.0)
    if cooldown <= 0:
        return 0.0

    last = domain_last_trigger.get(domain)
    if last is None:
        return 0.0

    elapsed = (current_dt - last).total_seconds()
    if elapsed < cooldown:
        return round(cooldown - elapsed, 2)
    return 0.0


def _check_rate_limit(
    domain: str,
    domain_last_trigger: dict[str, datetime],
    current_dt: datetime,
) -> float:
    """Check if rate limiting requires a delay."""
    limit = _RATE_LIMIT_PER_MINUTE_BY_DOMAIN.get(domain, 10)
    if limit <= 0:
        return 0.0

    min_interval = 60.0 / limit
    last = domain_last_trigger.get(domain)
    if last is None:
        return 0.0

    elapsed = (current_dt - last).total_seconds()
    if elapsed < min_interval:
        return round(min_interval - elapsed, 2)
    return 0.0


def _check_deferred(urgency: str) -> float:
    """Add delay for tasks with deferred urgency."""
    if urgency == "deferred":
        return _DEFERRED_URGENCY_DELAY_SECONDS
    return 0.0


def _parse_time(time_str: str) -> datetime:
    """Parse an ISO time string into a timezone-aware datetime."""
    return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
