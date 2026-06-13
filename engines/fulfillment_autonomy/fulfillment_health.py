"""Fulfillment health analyzer (Wave 128).

Thin wrapper over core/automation/health_analyzer.py. Uses
env_prefix='FULFILLMENT' for its thresholds:

  SHOPAI_AUTO_PAUSE_FULFILLMENT_ON_FAILURE=1
  SHOPAI_FULFILLMENT_WARN_FAILURE_RATIO=0.15
  SHOPAI_FULFILLMENT_PAUSE_FAILURE_RATIO=0.30
  SHOPAI_FULFILLMENT_HEALTH_MIN_SAMPLE=5
  SHOPAI_FULFILLMENT_AUTO_RESUME_HOURS=1.0
"""
from __future__ import annotations

from core.automation.health_analyzer import (
    HealthReport,
    analyze_health as _analyze,
    maybe_auto_pause as _maybe_pause,
)
from engines.fulfillment_autonomy.fulfillment_log import (
    recent_events,
)
from engines.fulfillment_autonomy.fulfillment_state import (
    is_paused,
    pause as _pause_state,
)


_ENV_PREFIX = "FULFILLMENT"


def analyze_fulfillment_health(
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


def maybe_auto_pause_fulfillment(
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
