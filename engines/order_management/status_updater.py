"""Order Management Engine — status updater.

Manages order status transitions with validation of allowed state changes.

All transition logic is real and deterministic.
"""
from __future__ import annotations

import copy
import time
from typing import Any

# Valid status transitions: from_status -> set of allowed to_statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled", "on_hold"},
    "confirmed": {"processing", "on_hold"},
    "processing": {"fulfilled", "on_hold"},
    "fulfilled": {"shipped", "on_hold"},
    "shipped": {"delivered", "on_hold"},
    "delivered": {"on_hold"},
    "on_hold": {"pending", "confirmed", "processing", "fulfilled", "shipped", "cancelled"},
    "cancelled": set(),  # terminal state
}

_ALL_STATUSES = set(_VALID_TRANSITIONS.keys())


def update_status(
    order_id: str,
    new_status: str,
    current_status: str | None = None,
) -> dict[str, Any]:
    """Update the status of an order with transition validation.

    Args:
        order_id: The order ID.
        new_status: The desired new status.
        current_status: The current status (defaults to "pending").

    Returns:
        Structured dict with status update result.
    """
    try:
        previous = current_status or "pending"
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- Validate statuses are known ----
        if previous not in _ALL_STATUSES:
            return _fail(f"Unknown current status: {previous}")

        if new_status not in _ALL_STATUSES:
            return _fail(f"Unknown target status: {new_status}")

        # ---- Validate transition is allowed ----
        allowed = _VALID_TRANSITIONS.get(previous, set())
        if new_status not in allowed:
            return _fail(
                f"Invalid transition: {previous} -> {new_status}. "
                f"Allowed: {sorted(allowed) if allowed else 'none (terminal state)'}"
            )

        # ---- Build status history ----
        status_history = [
            {"status": previous, "timestamp": now_ts},
            {"status": new_status, "timestamp": now_ts},
        ]

        return {
            "status": "success",
            "current_status": new_status,
            "previous_status": previous,
            "status_history": status_history,
        }
    except Exception as exc:
        return _fail(f"Status update failed: {exc}")


def _fail(reason: str) -> dict[str, Any]:
    """Return standardized error output."""
    return {
        "status": "error",
        "current_status": "",
        "previous_status": "",
        "status_history": [],
        "error": reason,
    }
