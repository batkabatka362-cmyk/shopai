"""Discount cleanup health analyzer (Wave 156)."""
from __future__ import annotations

from core.automation.health_analyzer import (
    HealthReport,
    analyze_health as _analyze,
    maybe_auto_pause as _maybe_pause,
)
from engines.discount_cleanup_autonomy.cleanup_log import (
    recent_events,
)
from engines.discount_cleanup_autonomy.cleanup_state import (
    is_paused,
    pause as _pause_state,
)


_ENV_PREFIX = "DISCOUNT_CLEANUP"


def analyze_cleanup_health(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> HealthReport:
    return _analyze(
        env_prefix=_ENV_PREFIX,
        window_hours=window_hours,
        recent_events_fn=recent_events,
        is_paused_fn=is_paused,
        store_id=store_id,
    )


def maybe_auto_pause_cleanup(
    *,
    window_hours: float = 24.0,
) -> HealthReport:
    return _maybe_pause(
        env_prefix=_ENV_PREFIX,
        window_hours=window_hours,
        recent_events_fn=recent_events,
        is_paused_fn=is_paused,
        pause_fn=_pause_state,
    )
