"""Goal feedback wiring — subscribe to approval-queue lifecycle and
feed outcomes into ``GoalManager.record_goal_outcome``.

The ``GoalManager`` already maintained per-goal effectiveness EMA
via ``record_goal_outcome(goal, metrics)``. Nothing was calling
it. This module closes that loop:

  1. Listens on ``approval.executed`` and ``approval.failed`` via
     the hooks dispatcher (PR #88).
  2. Maps each action's engine → primary goal
     (:mod:`core.goals.engine_goal_map`).
  3. Translates the approval result into signed deltas
     (``profit_delta`` / ``revenue_delta`` / ``health_delta``) that
     ``GoalManager.record_goal_outcome`` already consumes.

Wiring is **opt-in** to mirror the test-pollution-safe pattern
used elsewhere — ``register_goal_feedback()`` must be called
explicitly (typically at app startup) to attach the handlers.
Tests for the feedback module call it directly within an
``isolated_goal_manager`` fixture.

Engines without a primary-goal binding (see
:data:`core.goals.engine_goal_map.ENGINE_GOAL_MAP`) are silently
skipped so the global EMA isn't polluted by ambiguous attribution.

Failure outcomes always record under the engine's primary goal —
the system needs to learn that "this goal's recommended actions
are failing" not just "actions are failing". Crisis goals stay
sacrosanct in :meth:`GoalManager._evaluate_goals` regardless
(a D-grade situation always picks ``survive_crisis``).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("core.goals.feedback")


# Single-process singleton — registration is idempotent so
# re-importing this module doesn't double-attach.
_REGISTERED = False


def register_goal_feedback(
    *,
    manager: Any | None = None,
) -> bool:
    """Attach the lifecycle handlers to the hooks dispatcher.

    Args:
        manager: Optional :class:`core.goals.goal_manager.GoalManager`
            instance. Defaults to a module-level singleton lazily
            constructed on first call (the typical app-wide
            pattern). Tests pass a fresh instance.

    Returns:
        ``True`` when the handlers were registered (or already
        registered idempotently). ``False`` only when the hooks
        dispatcher is unavailable — in that case the feedback
        loop simply doesn't run and the rest of the system is
        unaffected.
    """
    global _REGISTERED
    if _REGISTERED:
        # Idempotent re-register. Helpful when multiple bootstrap
        # paths call this — only one set of handlers attaches.
        return True

    try:
        from core.hooks import register
    except Exception as exc:  # noqa: BLE001
        logger.debug("hooks dispatcher unavailable: %s", exc)
        return False

    resolved_manager = manager or _default_manager()
    if resolved_manager is None:
        logger.debug("goal manager unavailable; feedback NOT wired")
        return False

    def _on_executed(event: dict[str, Any]) -> None:
        _record_event(event, resolved_manager, succeeded=True)

    def _on_failed(event: dict[str, Any]) -> None:
        _record_event(event, resolved_manager, succeeded=False)

    def _on_outcome(event: dict[str, Any]) -> None:
        _record_outcome_event(event, resolved_manager)

    register("approval.executed", _on_executed)
    register("approval.failed", _on_failed)
    register("approval.outcome.recorded", _on_outcome)
    _REGISTERED = True
    logger.info(
        "goal-feedback handlers attached to approval.* hooks "
        "(executed/failed/outcome.recorded)",
    )
    return True


def reset_for_tests() -> None:
    """Drop the registered-flag. Tests use this to re-register
    against a fresh manager + fresh hooks registry per case.
    Production code should NOT call this — the feedback loop is
    intended to be a single attachment per process lifetime.
    """
    global _REGISTERED
    _REGISTERED = False


# ── Internal helpers ────────────────────────────────────────


def _record_event(
    event: dict[str, Any],
    manager: Any,
    *,
    succeeded: bool,
) -> None:
    """Translate one ``event`` into a ``record_goal_outcome`` call.

    Skips silently when:
      * The event data isn't a dict.
      * The engine field is missing / empty.
      * The engine has no primary-goal binding (unmapped engines
        don't contribute to any goal's EMA — see module docstring).

    Outcome metrics are derived from the approval result when the
    adapter surfaced revenue / profit deltas. Absent those, falls
    back to a single ``health_delta`` (+1 / -1) so success/failure
    still moves the EMA without claiming a precise dollar impact.
    """
    if not isinstance(event, dict):
        return
    data = event.get("data")
    if not isinstance(data, dict):
        return
    engine = str(data.get("engine", "")).strip()
    if not engine:
        return

    from core.goals.engine_goal_map import goal_for_engine
    goal = goal_for_engine(engine)
    if goal == "unmapped":
        logger.debug(
            "engine %r unmapped; skipping goal-feedback", engine,
        )
        return

    metrics = _derive_metrics(data.get("result"), succeeded=succeeded)
    try:
        manager.record_goal_outcome(goal, metrics)
    except Exception as exc:  # noqa: BLE001
        # The manager guards itself against bad input, but defend
        # against any other unexpected failure so a single
        # rogue feedback event can't crash the hooks fan-out.
        logger.debug(
            "record_goal_outcome raised for goal=%s: %s", goal, exc,
        )


def _record_outcome_event(
    event: dict[str, Any], manager: Any,
) -> None:
    """Translate an ``approval.outcome.recorded`` event into a
    ``record_goal_outcome`` call.

    Polarity → signed metrics:
      * ``positive`` (orders/create, orders/paid) → +1 health,
        and ``+revenue`` if the webhook payload surfaced one
      * ``negative`` (orders/cancelled, refunds/create) → -1
        health, and ``-revenue`` if present
      * ``neutral`` (everything else) → 0 health, no revenue
        signal (drives no EMA movement either direction)

    This is the **downstream-reality** refinement of the brain
    stack's EMA — the existing approval.executed/failed handlers
    record the *mutation* outcome (did Shopify accept the call?);
    this handler records the *business* outcome (did customers
    actually use it?). An engine that mints discount codes
    nobody redeems shouldn't earn the same EMA as one whose codes
    drive sales.
    """
    if not isinstance(event, dict):
        return
    data = event.get("data")
    if not isinstance(data, dict):
        return
    engine = str(data.get("engine", "")).strip()
    if not engine:
        return

    from core.goals.engine_goal_map import goal_for_engine
    goal = goal_for_engine(engine)
    if goal == "unmapped":
        logger.debug(
            "engine %r unmapped; skipping outcome feedback", engine,
        )
        return

    polarity = str(data.get("polarity", "neutral")).lower()
    if polarity not in ("positive", "negative", "neutral"):
        polarity = "neutral"
    if polarity == "neutral":
        # Neutral outcomes (e.g. orders/updated) carry no signal
        # for EMA. Skip rather than recording a zero — would
        # otherwise inflate the EMA's sample count without moving
        # the mean.
        return

    metrics = _derive_outcome_metrics(
        polarity=polarity, raw_metrics=data.get("metrics"),
    )
    try:
        manager.record_goal_outcome(goal, metrics)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "record_goal_outcome raised for outcome event "
            "(goal=%s): %s", goal, exc,
        )


def _derive_outcome_metrics(
    *,
    polarity: str,
    raw_metrics: Any,
) -> dict[str, float]:
    """Map polarity + webhook-extracted metrics → signed deltas
    ``GoalManager.record_goal_outcome`` consumes.
    """
    metrics: dict[str, float] = {}
    # health_delta sign mirrors the executed/failed handler.
    metrics["health_delta"] = 1.0 if polarity == "positive" else -1.0
    if isinstance(raw_metrics, dict):
        rev = raw_metrics.get("revenue")
        if rev is not None:
            try:
                rev_f = float(rev)
                metrics["revenue_delta"] = (
                    rev_f if polarity == "positive" else -rev_f
                )
            except (TypeError, ValueError):
                pass
    return metrics


def _derive_metrics(
    result: Any, *, succeeded: bool,
) -> dict[str, float]:
    """Extract signed deltas from the approval result dict.

    Result shapes vary per applier; we look for any of the common
    keys and copy through what's there. When the result is empty
    or missing the financial fields, fall back to a single
    ``health_delta`` so the EMA still updates.

    Sign of the fallback:
      * ``succeeded=True``  →  +1.0
      * ``succeeded=False`` →  -1.0
    """
    metrics: dict[str, float] = {}
    if isinstance(result, dict):
        for key in ("profit_delta", "revenue_delta", "health_delta"):
            raw = result.get(key)
            if raw is None:
                continue
            try:
                metrics[key] = float(raw)
            except (TypeError, ValueError):
                continue

    if not metrics:
        # No financial signal in the result — use a single health
        # delta whose sign matches the executed / failed split.
        metrics["health_delta"] = 1.0 if succeeded else -1.0
    return metrics


def _default_manager() -> Any | None:
    """Lazy-import and singleton-cache the module-level
    ``GoalManager``. Returns ``None`` only if the import fails
    (which would mean the goals package is broken; the caller
    treats that as "feedback loop disabled" and proceeds).
    """
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is not None:
        return _DEFAULT_MANAGER
    try:
        from core.goals.goal_manager import GoalManager
    except Exception as exc:  # noqa: BLE001
        logger.debug("GoalManager import failed: %s", exc)
        return None
    _DEFAULT_MANAGER = GoalManager()
    return _DEFAULT_MANAGER


_DEFAULT_MANAGER: Any | None = None
