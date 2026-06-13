"""Catalog quality action log (Wave 436)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.automation.action_log import (
    log_size as _log_size,
    recent_events as _recent_events,
    record_event,
)


_LOG_PATH = Path("data") / "catalog_quality_log.json"


@dataclass
class CatalogQualityEvent:
    product_id: str
    store_id: str = ""
    action: str = ""        # tag_quality
    tag: str = ""
    signal_source: str = ""  # which engine flagged this
    applied: bool = False
    status: str = ""
    error: str = ""
    recorded_at: float = field(default_factory=time.time)


def record_quality_event(event: CatalogQualityEvent) -> None:
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
