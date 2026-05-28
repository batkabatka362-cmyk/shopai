"""Discount cleanup action log (Wave 154)."""
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


_LOG_PATH = Path("data") / "discount_cleanup_log.json"


@dataclass
class DiscountCleanupEvent:
    discount_id: str
    code: str = ""
    store_id: str = ""
    reason: str = ""              # expired / unused / deprecated
    applied: bool = False
    status: str = ""              # recorded / paused / adapter_failed
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def record_cleanup_event(event: DiscountCleanupEvent) -> None:
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
