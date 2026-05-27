"""Generic autonomy health analyzer (Wave 119).

Extracts the pattern from
``engines/returns_management/refund_health.py`` (Wave 103) and
``engines/roas_guardrails/budget_health.py`` (Wave 111).

Given a set of recent events with ``status`` and ``applied``
fields, classifies the loop's health:

  - ``healthy``  -- low adapter_failed rate, no spikes
  - ``degraded`` -- failure ratio above WARN threshold
  - ``critical`` -- failure ratio above PAUSE threshold

Plus a bridge that, when env-gated AND verdict=critical AND not
already paused, calls the supplied ``pause_fn`` to set the
domain's pause flag.

Caller supplies:
  - ``recent_events`` callable -> list[dict]
  - ``is_paused`` callable -> bool
  - ``pause_fn`` callable(reason, auto_resume_after) -> None
  - ``env_prefix`` (e.g. ``REFUND`` or ``BUDGET``)

Env knobs (auto-derived from env_prefix):
  SHOPAI_AUTO_PAUSE_{PREFIX}_ON_FAILURE=1
  SHOPAI_{PREFIX}_WARN_FAILURE_RATIO=0.15
  SHOPAI_{PREFIX}_PAUSE_FAILURE_RATIO=0.30
  SHOPAI_{PREFIX}_HEALTH_MIN_SAMPLE=5
  SHOPAI_{PREFIX}_AUTO_RESUME_HOURS=1.0
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable


_DEFAULT_WARN_RATIO = 0.15
_DEFAULT_PAUSE_RATIO = 0.30
_DEFAULT_MIN_SAMPLE = 5
_DEFAULT_AUTO_RESUME_HOURS = 1.0


@dataclass
class HealthReport:
    window_hours: float
    sample_size: int = 0
    applied_count: int = 0
    adapter_failed_count: int = 0
    failure_ratio: float = 0.0
    verdict: str = "healthy"
    reasons: list[str] = field(default_factory=list)
    already_paused: bool = False
    bridge_fired: bool = False
    bridge_reason: str = ""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_truthy(name: str) -> bool:
    raw = os.environ.get(name, "")
    return str(raw).strip().lower() in ("1", "true", "yes")


def analyze_health(
    *,
    env_prefix: str,
    window_hours: float,
    recent_events_fn: Callable[..., list[dict[str, Any]]],
    is_paused_fn: Callable[[], bool],
    store_id: str | None = None,
) -> HealthReport:
    """Compute the loop health verdict for the window."""
    rows = recent_events_fn(
        window_hours=window_hours, store_id=store_id,
    )
    report = HealthReport(window_hours=window_hours)
    report.sample_size = len(rows)
    report.already_paused = is_paused_fn()

    warn_ratio = _env_float(
        f"SHOPAI_{env_prefix}_WARN_FAILURE_RATIO",
        _DEFAULT_WARN_RATIO,
    )
    pause_ratio = _env_float(
        f"SHOPAI_{env_prefix}_PAUSE_FAILURE_RATIO",
        _DEFAULT_PAUSE_RATIO,
    )
    min_sample = _env_int(
        f"SHOPAI_{env_prefix}_HEALTH_MIN_SAMPLE",
        _DEFAULT_MIN_SAMPLE,
    )

    if report.sample_size < min_sample:
        report.verdict = "healthy"
        report.reasons.append(
            f"sample size {report.sample_size} < min "
            f"{min_sample}; insufficient data"
        )
        return report

    applied = 0
    adapter_failed = 0
    for r in rows:
        if r.get("applied") is True:
            applied += 1
        if r.get("status") == "adapter_failed":
            adapter_failed += 1

    report.applied_count = applied
    report.adapter_failed_count = adapter_failed
    if report.sample_size > 0:
        report.failure_ratio = round(
            adapter_failed / report.sample_size, 3,
        )

    if report.failure_ratio >= pause_ratio:
        report.verdict = "critical"
        report.reasons.append(
            f"adapter_failed ratio {report.failure_ratio:.0%} "
            f">= pause threshold {pause_ratio:.0%} "
            f"(n={report.sample_size})"
        )
    elif report.failure_ratio >= warn_ratio:
        report.verdict = "degraded"
        report.reasons.append(
            f"adapter_failed ratio {report.failure_ratio:.0%} "
            f">= warn threshold {warn_ratio:.0%}"
        )
    else:
        report.verdict = "healthy"
        report.reasons.append(
            f"adapter_failed ratio {report.failure_ratio:.0%} "
            f"< warn threshold {warn_ratio:.0%}"
        )

    return report


def maybe_auto_pause(
    *,
    env_prefix: str,
    window_hours: float,
    recent_events_fn: Callable[..., list[dict[str, Any]]],
    is_paused_fn: Callable[[], bool],
    pause_fn: Callable[..., Any],
) -> HealthReport:
    """Compute health + auto-pause when env-gated AND critical."""
    report = analyze_health(
        env_prefix=env_prefix,
        window_hours=window_hours,
        recent_events_fn=recent_events_fn,
        is_paused_fn=is_paused_fn,
    )

    if not _env_truthy(
        f"SHOPAI_AUTO_PAUSE_{env_prefix}_ON_FAILURE",
    ):
        report.bridge_reason = "bridge env-gate OFF"
        return report

    if report.already_paused:
        report.bridge_reason = "already_paused"
        return report

    if report.verdict != "critical":
        report.bridge_reason = (
            f"verdict={report.verdict}; threshold not crossed"
        )
        return report

    auto_resume_h = _env_float(
        f"SHOPAI_{env_prefix}_AUTO_RESUME_HOURS",
        _DEFAULT_AUTO_RESUME_HOURS,
    )
    auto_resume_at = (
        time.time() + auto_resume_h * 3600.0
        if auto_resume_h > 0 else 0.0
    )
    pause_fn(
        reason=(
            f"auto-pause: "
            f"{report.reasons[0] if report.reasons else 'critical'}"
        ),
        auto_resume_after=auto_resume_at,
    )
    report.bridge_fired = True
    report.bridge_reason = "auto-paused"
    report.already_paused = True
    return report
