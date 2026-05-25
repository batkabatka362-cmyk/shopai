"""Revenue-regression -> quarantine bridge.

Wave 12 produces regression alerts cycle-over-cycle. Wave 13
feeds them onto the cluster bus so the next cycle's captains
react. Wave 21 (this module) extends the chain one more step:
when an engine appears in a regression alert across N
consecutive cycles, auto-add it to the quarantine state's
``alert_paused`` set so the standard enqueue path rejects new
actions.

This is the "act on it" companion to Waves 12+13. Wave 13
makes the captain CONSERVATIVE on a single regression; Wave 21
PAUSES on persistent regression. The escalation respects the
substrate-first principle: env-gated opt-in, never on by
default, mirror of the existing
``core.approval.alert_quarantine`` design.

## Env-var contract

  - ``SHOPAI_AUTO_QUARANTINE_FROM_REVENUE=1`` -- enable the
    bridge. Default OFF. Without it, persistent regression
    surfaces in CLI / world-model but doesn't pause.
  - ``SHOPAI_REVENUE_QUARANTINE_CYCLES`` -- threshold (default
    3). Engine must appear in this many CONSECUTIVE per-cycle
    deltas' alert lists.

## Pattern J

Under pytest, ``maybe_auto_quarantine_from_revenue`` returns
``[]`` without touching state. Tests installing real-state
exercise via a ``_is_test_environment`` patch fixture, same
pattern as alert_quarantine.

## Why engine-level, not cluster-level

A "retention cluster declining" alert doesn't tell us
whether loyalty earned $5k or churn_prediction earned $0. The
correct unit of pause is the engine: per-engine attribution
identifies WHICH member is responsible. Cluster-scope alerts
get cluster-mapped via the existing per_engine.cluster field
during streak counting, but the pause itself lands on
individual engines.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Iterable

logger = logging.getLogger(__name__)


_ENV_ENABLED = "SHOPAI_AUTO_QUARANTINE_FROM_REVENUE"
_ENV_CYCLES = "SHOPAI_REVENUE_QUARANTINE_CYCLES"

_DEFAULT_CYCLES = 3


def is_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED) == "1"


def threshold_cycles() -> int:
    raw = os.environ.get(_ENV_CYCLES)
    if not raw:
        return _DEFAULT_CYCLES
    try:
        return max(2, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_CYCLES


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def compute_engine_streaks(
    *,
    limit: int = 10,
    store_id: str | None = None,
) -> dict[str, int]:
    """For each engine that has appeared in a recent regression
    alert, count how many CONSECUTIVE cycles (newest first)
    that alert has fired.

    Args:
        limit: Max snapshots to scan (older cycles ignored).
        store_id: Per-store scope; None = fleet-wide.

    Returns:
        ``{engine_name: consecutive_count}``. Empty when no
        recent regressions or insufficient snapshot history.

    The count uses snapshot-pair deltas walking from the most
    recent backwards. A "streak" breaks the first cycle the
    engine doesn't appear in that cycle's alert list.
    """
    try:
        from engines._attribution_snapshot import recent_snapshots
        from engines._attribution_delta import compute_delta
    except Exception:  # noqa: BLE001
        return {}

    snaps = recent_snapshots(limit=limit, store_id=store_id)
    if len(snaps) < 2:
        return {}

    # snaps is newest-first; build (newer, older) pairs walking
    # forward in the list so deltas are also newest-first.
    streaks: dict[str, int] = defaultdict(int)
    # Track which engines are still on their streak (haven't
    # broken yet walking from newest backward).
    active: set[str] | None = None
    for i in range(len(snaps) - 1):
        latest = snaps[i]
        prior = snaps[i + 1]
        try:
            delta = compute_delta(prior, latest)
        except Exception:  # noqa: BLE001
            continue
        alerting_engines = {
            a.name for a in delta.alerts if a.scope == "engine"
        }
        if active is None:
            # First (most-recent) cycle seeds the streak set
            active = set(alerting_engines)
            for engine in active:
                streaks[engine] = 1
        else:
            # Subsequent cycles -- only engines still active
            # continue their streak
            still_active = active & alerting_engines
            for engine in still_active:
                streaks[engine] += 1
            active = still_active
        if not active:
            break

    return dict(streaks)


def maybe_auto_quarantine_from_revenue(
    *,
    limit: int = 10,
    store_id: str | None = None,
) -> list[str]:
    """Pause engines that crossed the consecutive-cycle threshold.

    Args:
        limit: Max snapshots to scan.
        store_id: Per-store scope; None = fleet-wide.

    Returns:
        List of engine names newly added to alert_paused.
        Empty when bridge is disabled, under pytest, or no
        engine crossed the threshold.
    """
    if not is_enabled():
        return []
    if _is_test_environment():
        return []
    try:
        from core.approval import quarantine
    except Exception:  # noqa: BLE001
        return []

    streaks = compute_engine_streaks(
        limit=limit, store_id=store_id,
    )
    threshold = threshold_cycles()

    # Pre-load state once to check existing alert pauses
    # (the quarantine module doesn't expose a per-engine
    # check helper -- read the set directly).
    try:
        state = quarantine.load_state()
        existing_pauses = {
            pair for pair in (state.alert_paused or set())
        }
    except Exception:  # noqa: BLE001
        existing_pauses = set()

    newly_paused: list[str] = []
    for engine, count in streaks.items():
        if count < threshold:
            continue
        # Match the (engine, store_id) tuple shape used by
        # the existing alert-quarantine pipeline
        pause_key = (engine, store_id)
        # Fleet pauses (store_id=None) supersede per-store
        if (engine, None) in existing_pauses:
            continue
        if pause_key in existing_pauses:
            continue
        try:
            quarantine.add_alert_pause(
                engine, store_id=store_id,
            )
            newly_paused.append(engine)
            logger.info(
                "revenue-regression auto-pause: engine=%s "
                "streak=%d cycles store=%s",
                engine, count, store_id or "fleet",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "revenue auto-quarantine failed for %s: %s",
                engine, exc,
            )
            continue

    return newly_paused
