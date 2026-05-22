"""Autonomous-cycle health alerts.

The cycle_history layer persists every invocation. This
module reads that log and detects HEALTH problems the
operator should know about. Four alert kinds:

  - ``stale_cycle`` -- no cycle ran in the staleness
    window (default 24h). The cron is broken or the
    operator forgot to wire it.
  - ``cycle_silent`` -- ZERO invocations in the broader
    window (default 7 days). The cycle has never run
    here, OR the history file got wiped.
  - ``low_advance_rate`` -- across recent cycles, ADVANCE
    phase refused/errored on most stores. Substrate is
    bricked or reliability threshold is too tight.
  - ``substrate_shrinking`` -- DEFEND phase has demoted
    far more capabilities than it has released. The bridge
    is too aggressive OR something is structurally wrong.

Pure read layer. Sister to ``core.approval.outcome_trends.
compute_engine_alerts`` -- same shape, same surface, but for
cycle-level rather than engine-level health.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from core.autonomous import cycle_history

logger = logging.getLogger(__name__)


_ENV_STALE_HOURS = "SHOPAI_CYCLE_STALE_HOURS"
_ENV_MIN_ADVANCE_RATE = "SHOPAI_CYCLE_MIN_ADVANCE_RATE"
_ENV_DEMOTE_RATIO = "SHOPAI_CYCLE_DEMOTE_RATIO_LIMIT"

_DEFAULT_STALE_HOURS = 24
_DEFAULT_MIN_ADVANCE_RATE = 0.5
_DEFAULT_DEMOTE_RATIO_LIMIT = 5.0


@dataclass
class CycleAlert:
    """One cycle-health alert. ``kind`` identifies the
    alert class; ``detail`` is a free-form summary string
    suitable for daily-brief rendering."""

    kind: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def stale_hours_threshold() -> int:
    raw = os.environ.get(_ENV_STALE_HOURS)
    if not raw:
        return _DEFAULT_STALE_HOURS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_STALE_HOURS, raw,
            _DEFAULT_STALE_HOURS, exc,
        )
        return _DEFAULT_STALE_HOURS


def min_advance_rate_threshold() -> float:
    raw = os.environ.get(_ENV_MIN_ADVANCE_RATE)
    if not raw:
        return _DEFAULT_MIN_ADVANCE_RATE
    try:
        v = float(raw)
        if v <= 0 or v > 1.0:
            return _DEFAULT_MIN_ADVANCE_RATE
        return v
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %s (%s)",
            _ENV_MIN_ADVANCE_RATE, raw,
            _DEFAULT_MIN_ADVANCE_RATE, exc,
        )
        return _DEFAULT_MIN_ADVANCE_RATE


def demote_ratio_limit() -> float:
    """When demoted_total / max(released_total, 1) exceeds
    this, fire substrate_shrinking alert. Default 5.0 (5
    demotes per release is meaningfully imbalanced)."""
    raw = os.environ.get(_ENV_DEMOTE_RATIO)
    if not raw:
        return _DEFAULT_DEMOTE_RATIO_LIMIT
    try:
        v = float(raw)
        if v < 1.0:
            return _DEFAULT_DEMOTE_RATIO_LIMIT
        return v
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %s (%s)",
            _ENV_DEMOTE_RATIO, raw,
            _DEFAULT_DEMOTE_RATIO_LIMIT, exc,
        )
        return _DEFAULT_DEMOTE_RATIO_LIMIT


def compute_cycle_alerts(
    *,
    window_seconds: int = 86400 * 7,
    now: float | None = None,
) -> list[CycleAlert]:
    """Inspect cycle history; emit a list of CycleAlerts.

    Args:
        window_seconds: Look-back window. Default 7 days.
        now: Override timestamp for testing.

    Returns:
        Newest-relevant-first list. Empty when everything
        is healthy.
    """
    try:
        stats = cycle_history.cycle_stats(
            since_seconds=window_seconds, now=now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compute_cycle_alerts: stats raised: %s", exc,
        )
        return []

    import time as _time
    now_t = now if now is not None else _time.time()
    alerts: list[CycleAlert] = []

    # Alert: cycle_silent -- nothing in the window at all
    if stats["total_runs"] == 0:
        alerts.append(CycleAlert(
            kind="cycle_silent",
            detail=(
                f"No cycle runs in the last "
                f"{window_seconds // 86400} day(s). "
                "Cron not wired, or history was cleared."
            ),
            metrics={"window_days": window_seconds // 86400},
        ))
        # Skip the other alerts -- they don't apply with
        # zero data.
        return alerts

    # Alert: stale_cycle -- last run too long ago
    stale_h = stale_hours_threshold()
    last_at = stats.get("last_run_at")
    if last_at is not None:
        age_hours = (now_t - float(last_at)) / 3600.0
        if age_hours > stale_h:
            alerts.append(CycleAlert(
                kind="stale_cycle",
                detail=(
                    f"Last cycle ran {age_hours:.1f}h ago "
                    f"(>{stale_h}h threshold). Cron may be "
                    "broken."
                ),
                metrics={
                    "age_hours": round(age_hours, 1),
                    "threshold_hours": stale_h,
                },
            ))

    # Alert: low_advance_rate -- across executed cycles,
    # most stores were refused/errored
    executed = stats["executed_runs"]
    if executed >= 3:
        advanced = stats["stores_advanced_total"]
        refused = stats["stores_refused_total"]
        denominator = advanced + refused
        if denominator > 0:
            rate = advanced / denominator
            threshold = min_advance_rate_threshold()
            if rate < threshold:
                alerts.append(CycleAlert(
                    kind="low_advance_rate",
                    detail=(
                        f"ADVANCE phase succeeded on "
                        f"{rate * 100:.0f}% of stores over "
                        f"{executed} executed cycles "
                        f"(threshold {threshold * 100:.0f}%). "
                        "Reliability gate may be too tight."
                    ),
                    metrics={
                        "advance_rate": round(rate, 3),
                        "threshold": threshold,
                        "executed_cycles": executed,
                        "advanced": advanced,
                        "refused": refused,
                    },
                ))

    # Alert: substrate_shrinking -- demote outpacing
    # release. Only meaningful if any demotes happened.
    demoted = stats["demoted_total"]
    released = stats["released_total"]
    if demoted >= 3:
        ratio = demoted / max(released, 1)
        limit = demote_ratio_limit()
        if ratio > limit:
            alerts.append(CycleAlert(
                kind="substrate_shrinking",
                detail=(
                    f"DEFEND phase demoted {demoted} "
                    f"capabilities vs {released} released "
                    f"(ratio {ratio:.1f}x, limit {limit:.1f}x). "
                    "Bridge may be over-tight, or substrate "
                    "is degrading faster than recovering."
                ),
                metrics={
                    "demoted": demoted,
                    "released": released,
                    "ratio": round(ratio, 2),
                    "limit": limit,
                },
            ))

    # Alert: promote_demote_thrashing -- capabilities
    # cycling between promote and demote. Investigate
    # manually. Surfaces alongside the other cycle alerts
    # so daily-brief / status pick it up automatically.
    try:
        from core.capability_planner import (
            auto_promote as _ap,
        )
        thrashing = _ap.find_promote_demote_cycles(
            window_seconds=window_seconds,
        )
        if thrashing:
            names = ", ".join(
                r["capability"] for r in thrashing[:3]
            )
            if len(thrashing) > 3:
                names += (
                    f", +{len(thrashing) - 3} more"
                )
            alerts.append(CycleAlert(
                kind="promote_demote_thrashing",
                detail=(
                    f"{len(thrashing)} capability(s) "
                    f"cycling between promote/demote: "
                    f"{names}. Manual review needed."
                ),
                metrics={
                    "count": len(thrashing),
                    "capabilities": [
                        r["capability"]
                        for r in thrashing
                    ],
                },
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compute_cycle_alerts: thrashing lookup "
            "raised: %s", exc,
        )

    return alerts


def config_summary() -> dict[str, Any]:
    return {
        "stale_hours_threshold": stale_hours_threshold(),
        "min_advance_rate_threshold": (
            min_advance_rate_threshold()
        ),
        "demote_ratio_limit": demote_ratio_limit(),
    }


@dataclass
class PerStoreCycleAlert:
    """One store-level cycle alert. Same shape as
    CycleAlert but scoped to a specific store_id."""

    store_id: str
    kind: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


def compute_per_store_alerts(
    *,
    window_seconds: int = 86400 * 7,
    min_attempts: int = 3,
    now: float | None = None,
) -> list[PerStoreCycleAlert]:
    """Detect per-store cycle health issues from
    cycle_history's per_store_stats.

    Currently emits two alert kinds:
      - ``store_consistently_refused`` -- store has been
        attempted ``min_attempts``+ times and the
        advance-rate is below the fleet-wide threshold
        (``SHOPAI_CYCLE_MIN_ADVANCE_RATE``). Store-specific
        reliability gate may be too tight.
      - ``store_consistently_errored`` -- store has errored
        on ``min_attempts``+ cycles in the window. Likely
        infrastructure / credentials / scope issue rather
        than substrate.

    Args:
        window_seconds: Look-back window (default 7 days).
        min_attempts: Minimum cycle attempts before
            considering a store for alerting (default 3 --
            single bad cycle isn't a pattern).
        now: Override timestamp for testing.

    Returns:
        List sorted by (kind, store_id) for stable output.
        Empty when every store is healthy.
    """
    try:
        per_store = cycle_history.per_store_stats(
            since_seconds=window_seconds, now=now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "compute_per_store_alerts: stats raised: %s",
            exc,
        )
        return []

    if not per_store:
        return []

    advance_threshold = min_advance_rate_threshold()
    alerts: list[PerStoreCycleAlert] = []
    for sid, stats in per_store.items():
        total = int(stats.get("total", 0) or 0)
        if total < max(1, int(min_attempts)):
            continue
        executed = int(stats.get("executed", 0) or 0)
        refused = int(stats.get("refused", 0) or 0)
        errored = int(stats.get("errored", 0) or 0)

        # store_consistently_errored: more than half of
        # attempts errored
        if total > 0 and errored / total >= 0.5:
            alerts.append(PerStoreCycleAlert(
                store_id=sid,
                kind="store_consistently_errored",
                detail=(
                    f"{errored}/{total} cycles errored on "
                    f"this store. Check credentials / "
                    f"scope / connectivity."
                ),
                metrics={
                    "errored": errored,
                    "total": total,
                    "error_rate": round(
                        errored / total, 3,
                    ),
                },
            ))
            # Don't double-alert as refused -- errored is
            # the dominant signal
            continue

        # store_consistently_refused: advance-rate below
        # threshold. Denominator excludes errored (those
        # didn't get a fair chance to advance).
        attemptable = executed + refused
        if attemptable >= max(1, int(min_attempts)):
            rate = executed / attemptable
            if rate < advance_threshold:
                alerts.append(PerStoreCycleAlert(
                    store_id=sid,
                    kind="store_consistently_refused",
                    detail=(
                        f"ADVANCE succeeded on "
                        f"{rate * 100:.0f}% of cycles for "
                        f"this store ({executed}/"
                        f"{attemptable}). Reliability gate "
                        "may be too tight for this store."
                    ),
                    metrics={
                        "executed": executed,
                        "refused": refused,
                        "advance_rate": round(rate, 3),
                        "threshold": advance_threshold,
                    },
                ))

    alerts.sort(key=lambda a: (a.kind, a.store_id))
    return alerts
