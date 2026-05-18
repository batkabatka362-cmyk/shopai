"""Alert-history → quarantine bridge.

PR #292 added ``core.approval.alert_history``: a persistent log
of engine-degradation alert firings. PR #293 wired
``daily-brief`` to record every alert into that log.

This module closes the loop: when an engine has fired
degradation alerts on ``N`` distinct days within the window,
auto-add it to the quarantine state's ``alert_paused`` set so
``ApprovalQueue.enqueue``'s standard quarantine check rejects
new actions until an operator clears the pause.

The integration point is intentionally separate from
``core.approval.quarantine.evaluate`` (which is outcome-based,
not alert-based). Two complementary safety nets, one shared
state file, one shared rejection path.

Env-var contract (Pattern J safety):

  - ``SHOPAI_AUTO_QUARANTINE_FROM_ALERTS=1`` -- enables the
    bridge. Default OFF. Without it, even repeated firings
    don't auto-pause -- the operator still sees them via
    ``daily-brief``'s ``consecutive_days`` field.
  - ``SHOPAI_AUTO_QUARANTINE_DAYS`` -- threshold (default 3).
    Engine must have fired on this many distinct days within
    the window to auto-pause.
  - ``SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS`` -- detection window
    (default 7). Wider = more lenient; narrower = stricter.

Pattern J: under pytest, ``maybe_auto_quarantine_from_alerts``
returns ``[]`` without touching state. Tests exercising the
bridge install an autouse fixture that patches
``_is_test_environment`` to ``False``.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

from core.approval import alert_history, quarantine

logger = logging.getLogger(__name__)


_ENV_ENABLED = "SHOPAI_AUTO_QUARANTINE_FROM_ALERTS"
_ENV_DAYS = "SHOPAI_AUTO_QUARANTINE_DAYS"
_ENV_WINDOW = "SHOPAI_AUTO_QUARANTINE_WINDOW_DAYS"

_DEFAULT_DAYS = 3
_DEFAULT_WINDOW_DAYS = 7


def is_enabled() -> bool:
    """Bridge is opt-in. Operator sets the env var when ready
    to delegate the auto-pause decision."""
    return os.environ.get(_ENV_ENABLED) == "1"


def threshold_days() -> int:
    raw = os.environ.get(_ENV_DAYS)
    if not raw:
        return _DEFAULT_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_DAYS, raw, _DEFAULT_DAYS, exc,
        )
        return _DEFAULT_DAYS


def window_days() -> int:
    raw = os.environ.get(_ENV_WINDOW)
    if not raw:
        return _DEFAULT_WINDOW_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError) as exc:
        logger.debug(
            "invalid %s=%r; using default %d (%s)",
            _ENV_WINDOW, raw, _DEFAULT_WINDOW_DAYS, exc,
        )
        return _DEFAULT_WINDOW_DAYS


def _is_test_environment() -> bool:
    """Pattern J — bridge must never auto-pause under pytest.
    Tests that need to exercise the integration patch this."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def engines_to_pause(*, now: float | None = None) -> list[str]:
    """Pure read: engines that WOULD be auto-paused right now,
    given the current alert history + quarantine state.

    Skips engines already on any of:
      - ``exemptions`` (operator says never quarantine)
      - ``alert_paused`` (already paused via this bridge)

    Note: engines on the ``released`` list ARE returned -- a
    re-pause after operator release is the intended signal that
    the underlying issue didn't actually get fixed. The
    operator can re-release explicitly if that's wrong.
    """
    if not is_enabled():
        return []
    threshold = threshold_days()
    window = window_days()
    consecutive = alert_history.consecutive_runs_per_engine(
        window_seconds=window * 86400.0,
        bucket_seconds=86400.0,
        now=now,
    )
    state = quarantine.load_state()
    out: list[str] = []
    for engine, days in consecutive.items():
        if days < threshold:
            continue
        if state.is_exempt(engine):
            continue
        if state.is_alert_paused(engine):
            continue
        out.append(engine)
    out.sort()
    return out


def apply_pauses(engines: Iterable[str]) -> list[str]:
    """Persist each engine into the quarantine state's
    ``alert_paused`` set. Returns the engines actually paused
    (in case ``add_alert_pause`` raises on one)."""
    paused: list[str] = []
    for engine in engines:
        try:
            quarantine.add_alert_pause(engine)
        except (ValueError, OSError) as exc:
            logger.debug(
                "alert_quarantine.apply_pauses failed for %s: %s",
                engine, exc,
            )
            continue
        paused.append(engine)
    return paused


def maybe_auto_quarantine_from_alerts(
    *, now: float | None = None,
) -> list[str]:
    """Compute + apply in one call. Pattern J guard returns
    ``[]`` under pytest. Returns the list of engines newly
    paused -- empty if disabled, already paused, or below
    threshold."""
    if _is_test_environment():
        return []
    if not is_enabled():
        return []
    engines = engines_to_pause(now=now)
    if not engines:
        return []
    return apply_pauses(engines)


def find_release_candidates(
    *,
    quiet_days: float | None = None,
    now: float | None = None,
) -> list[dict]:
    """Find alert-paused engines that have gone quiet.

    Sister to ``core.approval.quarantine.find_release_candidates``
    (which is OUTCOME-based). This one is ALERT-based: an
    operator looking at the alert_paused list wants to know
    which engines haven't fired any new degradation alerts
    recently and are safe to release.

    Args:
        quiet_days: How many days of silence before an engine
            is a candidate. Default: same as the bridge's
            window_days (so an engine that hasn't fired in the
            whole detection window is safe).
        now: Override timestamp for testing.

    Returns:
        Newest-last (= longest-quiet first). Each entry:
          {engine, days_since_last_alert, last_alert_at,
           recent_event_count}
        ``last_alert_at`` may be None if there's no recorded
        firing at all -- still a candidate (paused before the
        alert_history layer existed, or after a clear).
    """
    if now is None:
        import time
        now = time.time()
    quiet = quiet_days if quiet_days is not None else window_days()
    quiet_seconds = quiet * 86400.0

    state = quarantine.load_state()
    paused = sorted(state.alert_paused)
    if not paused:
        return []

    # Fetch a wide history window so we can find the last
    # firing for engines even if it was a long time ago.
    events = alert_history.recent_history(
        since_seconds=86400.0 * 365.0,
        now=now,
    )
    # Per-engine: newest event timestamp + count in the quiet
    # window.
    last_seen: dict[str, float] = {}
    recent_count: dict[str, int] = {}
    quiet_cutoff = now - quiet_seconds
    for e in events:
        if e.engine not in state.alert_paused:
            continue
        prior = last_seen.get(e.engine, 0.0)
        if e.recorded_at > prior:
            last_seen[e.engine] = e.recorded_at
        if e.recorded_at >= quiet_cutoff:
            recent_count[e.engine] = recent_count.get(
                e.engine, 0,
            ) + 1

    out: list[dict] = []
    for engine in paused:
        last = last_seen.get(engine)
        recent = recent_count.get(engine, 0)
        if recent > 0:
            # Still firing -- not safe to release.
            continue
        out.append({
            "engine": engine,
            "days_since_last_alert": (
                (now - last) / 86400.0 if last else None
            ),
            "last_alert_at": last,
            "recent_event_count": recent,
        })

    # Longest-quiet first (None days = oldest = no history)
    out.sort(
        key=lambda r: (
            r["days_since_last_alert"]
            if r["days_since_last_alert"] is not None
            else float("inf")
        ),
        reverse=True,
    )
    return out
