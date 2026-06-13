"""Fulfillment action log (Wave 126).

Thin wrapper over core/automation/action_log.py. Domain-
specific dataclass; persistence + query semantics come from
the generic substrate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any

from core.automation.action_log import (
    record_event,
    recent_events as _recent_events,
    log_size as _log_size,
)


_LOG_PATH = Path("data") / "fulfillment_log.json"


@dataclass
class FulfillmentEvent:
    order_id: str
    location_id: str = ""
    store_id: str = ""
    action: str = ""              # route / hold / cancel
    fulfillment_id: str = ""
    applied: bool = False
    status: str = ""              # recorded / paused / adapter_failed
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def record_fulfillment_event(event: FulfillmentEvent) -> None:
    record_event(_LOG_PATH, event)


def recent_events(
    *,
    window_hours: float = 168.0,
    store_id: str | None = None,
) -> list[dict[str, Any]]:
    return _recent_events(
        _LOG_PATH,
        window_hours=window_hours,
        filters={"store_id": store_id or ""},
    )


def log_size() -> int:
    return _log_size(_LOG_PATH)
