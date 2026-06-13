"""Auto-relax + auto-restore bridge for the reliability
threshold.

The next-action recommender (PR 6f2b2249) suggests lowering
the threshold when ``low_advance_rate`` has fired for 3+
consecutive days. The persistent override file (PR 079943e1)
lets operators apply the change without a restart. This
module closes the autonomous loop: env-gated, conservative,
self-correcting.

Two directions, opt-in independently:

  - **Relax** -- streak-detector sees a chronic
    low_advance_rate. Lower the persistent threshold by a
    configurable step, floored at a configurable minimum.
  - **Restore** -- alerts have been QUIET for N days after a
    prior relax. Raise the threshold back toward the
    operator's original value (ceiling).

Both directions are env-gated and default OFF. Each is a
separate decision -- enabling relax doesn't enable restore.

Env-var contract
----------------

  - ``SHOPAI_AUTO_RELAX_RELIABILITY=1`` -- enables both
    sides of the bridge. Default OFF.
  - ``SHOPAI_AUTO_RELAX_STREAK_DAYS`` -- streak threshold
    before relax fires. Default 3.
  - ``SHOPAI_AUTO_RELAX_STEP`` -- how much to lower per
    trigger. Default 0.05 (5pp).
  - ``SHOPAI_AUTO_RELAX_FLOOR`` -- never relax below this.
    Default 0.5.
  - ``SHOPAI_AUTO_RELAX_QUIET_DAYS`` -- how many days of
    silence before restore fires. Default 5.
  - ``SHOPAI_AUTO_RELAX_CEILING`` -- never restore above
    this. Default 0.9 (matches module default).

Pattern J: ``maybe_relax`` and ``maybe_restore`` short-
circuit under pytest. ``find_*_action`` previews always
compute regardless.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_ENV_ENABLED = "SHOPAI_AUTO_RELAX_RELIABILITY"
_ENV_STREAK_DAYS = "SHOPAI_AUTO_RELAX_STREAK_DAYS"
_ENV_STEP = "SHOPAI_AUTO_RELAX_STEP"
_ENV_FLOOR = "SHOPAI_AUTO_RELAX_FLOOR"
_ENV_QUIET_DAYS = "SHOPAI_AUTO_RELAX_QUIET_DAYS"
_ENV_CEILING = "SHOPAI_AUTO_RELAX_CEILING"

_DEFAULT_STREAK_DAYS = 3
_DEFAULT_STEP = 0.05
_DEFAULT_FLOOR = 0.5
_DEFAULT_QUIET_DAYS = 5
_DEFAULT_CEILING = 0.9


@dataclass
class RelaxAction:
    """One bridge decision. ``direction`` is ``relax`` /
    ``restore`` / ``none``. ``applied`` is the actual change
    that was written, or None on dry-run / blocked."""

    direction: str
    current_value: float
    proposed_value: float
    reason: str
    applied: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


def is_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED) == "1"


def streak_days_threshold() -> int:
    raw = os.environ.get(_ENV_STREAK_DAYS)
    if not raw:
        return _DEFAULT_STREAK_DAYS
    try:
        return max(2, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_STREAK_DAYS


def relax_step() -> float:
    raw = os.environ.get(_ENV_STEP)
    if not raw:
        return _DEFAULT_STEP
    try:
        v = float(raw)
        if v <= 0 or v > 0.5:
            return _DEFAULT_STEP
        return v
    except (TypeError, ValueError):
        return _DEFAULT_STEP


def relax_floor() -> float:
    raw = os.environ.get(_ENV_FLOOR)
    if not raw:
        return _DEFAULT_FLOOR
    try:
        v = float(raw)
        if v < 0 or v > 1.0:
            return _DEFAULT_FLOOR
        return v
    except (TypeError, ValueError):
        return _DEFAULT_FLOOR


def quiet_days_threshold() -> int:
    raw = os.environ.get(_ENV_QUIET_DAYS)
    if not raw:
        return _DEFAULT_QUIET_DAYS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_QUIET_DAYS


def relax_ceiling() -> float:
    raw = os.environ.get(_ENV_CEILING)
    if not raw:
        return _DEFAULT_CEILING
    try:
        v = float(raw)
        if v < 0 or v > 1.0:
            return _DEFAULT_CEILING
        return v
    except (TypeError, ValueError):
        return _DEFAULT_CEILING


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def find_relax_action(
    *,
    now: float | None = None,
) -> RelaxAction:
    """Read-only: compute whether a RELAX action is
    warranted right now.

    Returns a RelaxAction with ``direction='relax'`` if the
    conditions hold, or ``direction='none'`` otherwise. The
    ``applied`` field is always False for previews.
    """
    try:
        from core.autonomous import (
            cycle_alert_history as _cah,
            cycle_overrides as _co,
        )
    except ImportError as exc:
        logger.debug(
            "auto_relax: import failed: %s", exc,
        )
        return RelaxAction(
            direction="none",
            current_value=0.0,
            proposed_value=0.0,
            reason=f"import_failed: {exc}",
        )

    try:
        streaks = _cah.consecutive_days_per_kind(
            window_seconds=86400 * 14,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_relax: streak lookup raised: %s", exc,
        )
        streaks = {}

    streak = int(streaks.get("low_advance_rate", 0) or 0)
    threshold_days = streak_days_threshold()
    current = _co.resolve_threshold()
    floor = relax_floor()
    step = relax_step()

    if streak < threshold_days:
        return RelaxAction(
            direction="none",
            current_value=current,
            proposed_value=current,
            reason=(
                f"streak {streak}d below "
                f"{threshold_days}d threshold"
            ),
            metrics={"streak_days": streak},
        )

    proposed = round(max(current - step, floor), 4)
    if proposed >= current:
        # Already at floor (or below) -- nothing to do
        return RelaxAction(
            direction="none",
            current_value=current,
            proposed_value=current,
            reason=(
                f"threshold {current:.2f} already at "
                f"floor {floor:.2f}"
            ),
            metrics={
                "streak_days": streak,
                "floor": floor,
            },
        )

    return RelaxAction(
        direction="relax",
        current_value=current,
        proposed_value=proposed,
        reason=(
            f"low_advance_rate firing {streak}d "
            f"(>= {threshold_days}d threshold); "
            f"lower threshold by {step:.2f}"
        ),
        metrics={
            "streak_days": streak,
            "step": step,
            "floor": floor,
        },
    )


def find_restore_action(
    *,
    now: float | None = None,
) -> RelaxAction:
    """Read-only: compute whether a RESTORE action is
    warranted right now.

    Triggers when:
      - Override file currently has auto_execute_threshold
        BELOW the ceiling (i.e., a prior relax happened).
      - low_advance_rate has been quiet for >= quiet_days
        (no firings in the recent window).
    """
    try:
        from core.autonomous import (
            cycle_alert_history as _cah,
            cycle_overrides as _co,
        )
    except ImportError as exc:
        logger.debug(
            "auto_relax: import failed: %s", exc,
        )
        return RelaxAction(
            direction="none",
            current_value=0.0,
            proposed_value=0.0,
            reason=f"import_failed: {exc}",
        )

    current = _co.resolve_threshold()
    ceiling = relax_ceiling()
    step = relax_step()
    quiet_days = quiet_days_threshold()
    if current >= ceiling:
        return RelaxAction(
            direction="none",
            current_value=current,
            proposed_value=current,
            reason=(
                f"threshold {current:.2f} already at "
                f"ceiling {ceiling:.2f}"
            ),
        )

    # Check the override file directly. If
    # auto_execute_threshold is NOT in there, an env / default
    # is providing the current value -- not our place to
    # touch.
    overrides = _co.load_overrides()
    if "auto_execute_threshold" not in overrides:
        return RelaxAction(
            direction="none",
            current_value=current,
            proposed_value=current,
            reason=(
                "no persistent override set "
                "(restore acts only on prior relax writes)"
            ),
        )

    # Streak == 0 means no firings in the window. We look
    # at a window matching quiet_days.
    try:
        streaks = _cah.consecutive_days_per_kind(
            window_seconds=quiet_days * 86400,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_relax: streak lookup raised: %s", exc,
        )
        streaks = {}

    fires = int(streaks.get("low_advance_rate", 0) or 0)
    if fires > 0:
        return RelaxAction(
            direction="none",
            current_value=current,
            proposed_value=current,
            reason=(
                f"low_advance_rate fired in last "
                f"{quiet_days}d ({fires} day(s))"
            ),
            metrics={
                "recent_fires": fires,
                "quiet_days": quiet_days,
            },
        )

    proposed = round(min(current + step, ceiling), 4)
    return RelaxAction(
        direction="restore",
        current_value=current,
        proposed_value=proposed,
        reason=(
            f"low_advance_rate quiet for >= "
            f"{quiet_days}d; raise threshold by "
            f"{step:.2f} toward ceiling {ceiling:.2f}"
        ),
        metrics={
            "quiet_days": quiet_days,
            "step": step,
            "ceiling": ceiling,
        },
    )


def maybe_apply(
    action: RelaxAction,
) -> RelaxAction:
    """Apply a previously-computed action.

    Pattern J short-circuits under pytest -- the action's
    ``applied`` field stays False.

    Direction ``none`` is a no-op (returns input unchanged).
    Direction ``relax`` / ``restore`` calls
    ``cycle_overrides.set_override`` to persist the new
    threshold. Sets ``applied=True`` on successful write.

    Env gate ``SHOPAI_AUTO_RELAX_RELIABILITY=1`` required
    for the write to fire.
    """
    if action.direction == "none":
        return action
    if _is_test_environment():
        return action
    if not is_enabled():
        return action
    try:
        from core.autonomous import (
            cycle_overrides as _co,
        )
        ok = _co.set_override(
            "auto_execute_threshold",
            action.proposed_value,
        )
        if ok:
            action.applied = True
            # Audit trail: log the applied action so future
            # operators can answer "why is my threshold at
            # 0.65?". Best-effort: history failures don't
            # invalidate the override write.
            try:
                from core.autonomous import (
                    auto_relax_history as _arh,
                )
                _arh.record_action(
                    direction=action.direction,
                    current_value=action.current_value,
                    proposed_value=action.proposed_value,
                    reason=action.reason,
                    metrics=action.metrics,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "auto_relax: history record "
                    "raised: %s", exc,
                )
        else:
            logger.debug(
                "auto_relax: set_override returned "
                "False (test env or I/O error)",
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "auto_relax: apply raised: %s", exc,
        )
    return action


def maybe_relax_and_restore(
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Convenience: compute + maybe-apply both directions in
    one call. Returns a summary suitable for inclusion in
    the cycle summary.

    Restore is checked first (cheaper bail), then relax.
    Either or neither may fire; both can never fire on the
    same run because they require contradictory states (one
    needs persistent fires, the other needs quiet).
    """
    if now is None:
        now = time.time()
    restore = find_restore_action(now=now)
    if restore.direction == "restore":
        restore = maybe_apply(restore)
        return {
            "checked": True,
            "enabled": is_enabled(),
            "direction": "restore",
            "current_value": restore.current_value,
            "proposed_value": restore.proposed_value,
            "applied": restore.applied,
            "reason": restore.reason,
            "metrics": restore.metrics,
        }
    relax = find_relax_action(now=now)
    if relax.direction == "relax":
        relax = maybe_apply(relax)
        return {
            "checked": True,
            "enabled": is_enabled(),
            "direction": "relax",
            "current_value": relax.current_value,
            "proposed_value": relax.proposed_value,
            "applied": relax.applied,
            "reason": relax.reason,
            "metrics": relax.metrics,
        }
    return {
        "checked": True,
        "enabled": is_enabled(),
        "direction": "none",
        "current_value": relax.current_value,
        "proposed_value": relax.current_value,
        "applied": False,
        "reason": relax.reason,
        "metrics": relax.metrics,
    }


def config_summary() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "streak_days_threshold": streak_days_threshold(),
        "relax_step": relax_step(),
        "relax_floor": relax_floor(),
        "quiet_days_threshold": quiet_days_threshold(),
        "relax_ceiling": relax_ceiling(),
    }
