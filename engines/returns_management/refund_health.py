"""Refund health analyzer (Wave 103).

Reads ``data/refund_log.json`` entries from the recent window
and classifies the autonomous refund loop's health:

  - ``healthy``  -- low failure rate, no spikes
  - ``degraded`` -- adapter_failed rate above WARN threshold
  - ``critical`` -- adapter_failed rate above PAUSE threshold;
                    auto-pause bridge would fire

Plus a bridge function ``maybe_auto_pause_refunds()`` that:
  1. Reads env gate (default OFF)
  2. Computes health verdict
  3. If critical AND env-gated, calls refund_state.pause()
  4. Returns the bridge outcome

The bridge is opt-in by design -- a single bad refund batch
shouldn't auto-pause without operator awareness. Default flow
is read-only diagnostic; ``SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE
=1`` enables auto-pause.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from engines.returns_management.refund_log import recent_refunds
from engines.returns_management.refund_state import (
    is_paused, pause,
)


# Default thresholds (overrideable via env)
_DEFAULT_WARN_RATIO = 0.15      # 15% adapter_failed -> warn
_DEFAULT_PAUSE_RATIO = 0.30     # 30% adapter_failed -> pause
_DEFAULT_MIN_SAMPLE = 5         # need >=5 entries to act
_DEFAULT_AUTO_RESUME_HOURS = 1.0


@dataclass
class RefundHealthReport:
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


def analyze_refund_health(
    *,
    window_hours: float = 24.0,
    store_id: str | None = None,
) -> RefundHealthReport:
    """Compute the refund-loop health verdict for the window.

    Read-only. Does NOT trigger the auto-pause bridge -- that's
    ``maybe_auto_pause_refunds()``.
    """
    rows = recent_refunds(
        window_hours=window_hours, store_id=store_id,
    )
    report = RefundHealthReport(window_hours=window_hours)
    report.sample_size = len(rows)
    report.already_paused = is_paused()

    warn_ratio = _env_float(
        "SHOPAI_REFUND_WARN_FAILURE_RATIO",
        _DEFAULT_WARN_RATIO,
    )
    pause_ratio = _env_float(
        "SHOPAI_REFUND_PAUSE_FAILURE_RATIO",
        _DEFAULT_PAUSE_RATIO,
    )
    min_sample = _env_int(
        "SHOPAI_REFUND_HEALTH_MIN_SAMPLE",
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


def maybe_auto_pause_refunds(
    *,
    window_hours: float = 24.0,
) -> RefundHealthReport:
    """Compute health + auto-pause if env-gated AND critical.

    Operator runs this on a schedule (cron / cycle hook). The
    function is idempotent: if refunds are already paused, the
    bridge skips with bridge_fired=False, bridge_reason=
    'already_paused'.
    """
    report = analyze_refund_health(window_hours=window_hours)

    if not _env_truthy("SHOPAI_AUTO_PAUSE_REFUNDS_ON_FAILURE"):
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
        "SHOPAI_REFUND_AUTO_RESUME_HOURS",
        _DEFAULT_AUTO_RESUME_HOURS,
    )
    auto_resume_at = (
        time.time() + auto_resume_h * 3600.0
        if auto_resume_h > 0 else 0.0
    )
    pause(
        reason=(
            f"auto-pause: {report.reasons[0] if report.reasons else 'critical health'}"
        ),
        auto_resume_after=auto_resume_at,
    )
    report.bridge_fired = True
    report.bridge_reason = "auto-paused"
    report.already_paused = True
    return report
