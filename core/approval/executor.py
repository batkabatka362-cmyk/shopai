"""Replay APPROVED actions through their engine appliers.

Closes the loop the approval queue (PR #57) and the nine engine
wireups (PR #59 / #60 / #61 / #63 / #64 / #65 / #66 / #67 / #68)
opened. Pre-executor an APPROVED action just sits in the queue
— the merchant clicked approve but nothing actually executes.

This module provides the missing handoff:

    enqueue (engine)  →  pending
    approve (api)     →  approved
    execute (executor) → executed | failed       ← here

Design:

  * A registry maps ``action_type`` → callable that takes the
    parked ``params`` dict and returns ``(success, result_dict)``.
  * Each registration lives in :mod:`core.approval.dispatchers`
    next to a tiny per-action adapter function — keeps the
    executor itself dispatcher-agnostic.
  * ``execute_action(action_id)`` loads the action, refuses
    anything not in ``APPROVED`` state (idempotent — a second
    execute returns the current snapshot without re-running),
    invokes the dispatcher, and calls
    :meth:`ApprovalQueue.attach_result` to flip status to
    ``EXECUTED`` or ``FAILED``.
  * Dispatcher exceptions are caught — a runaway dispatcher
    must not leak. Failure surfaces as ``status=FAILED`` with
    the exception text in ``result.error``.

The dispatchers all live behind lazy imports inside their
register functions so this module stays cheap to import — same
pattern the engines use to keep ``record_writeback`` lightweight.
"""
from __future__ import annotations

from typing import Any, Callable

from utils.logger import get_logger

from core.approval.queue import (
    ApprovalAction,
    ApprovalStatus,
    get_approval_queue,
)

logger = get_logger("core.approval.executor")

# action_type → (params: dict) -> (success: bool, result: dict)
DispatcherFn = Callable[[dict[str, Any]], tuple[bool, dict[str, Any]]]
_DISPATCHERS: dict[str, DispatcherFn] = {}


def register_dispatcher(action_type: str) -> Callable[[DispatcherFn], DispatcherFn]:
    """Decorator: bind a dispatcher to an ``action_type``.

    Usage::

        @register_dispatcher("apply_tags")
        def _apply_tags_dispatcher(params: dict) -> tuple[bool, dict]:
            ...

    Re-registration overwrites silently (test fixtures may need
    to substitute stubs).
    """
    def decorator(fn: DispatcherFn) -> DispatcherFn:
        _DISPATCHERS[action_type] = fn
        return fn
    return decorator


def list_registered_action_types() -> list[str]:
    """Snapshot of action_types the executor can dispatch.

    Used by the API status endpoint and by tests that want to
    verify the registry is fully wired.
    """
    return sorted(_DISPATCHERS.keys())


def execute_action(action_id: str) -> ApprovalAction | None:
    """Replay an APPROVED action through its registered dispatcher.

    Args:
        action_id: id of the queued action.

    Returns:
        Updated :class:`ApprovalAction` reflecting EXECUTED /
        FAILED state, or ``None`` if the id is unknown or the
        action isn't in APPROVED state. Callers can treat
        ``None`` as a no-op (idempotent — re-executing an
        already-resolved action returns ``None``, the original
        state is preserved).
    """
    # Trigger dispatcher registration on first call. Cheap — the
    # module just appends to ``_DISPATCHERS``.
    _ensure_dispatchers_loaded()

    queue = get_approval_queue()
    action = queue.get(action_id)
    if action is None:
        logger.debug("execute_action no-op: id %s not found", action_id)
        return None
    if action.status != ApprovalStatus.APPROVED:
        logger.debug(
            "execute_action no-op: %s is in %s state",
            action_id, action.status.value,
        )
        return None

    dispatcher = _DISPATCHERS.get(action.action_type)
    if dispatcher is None:
        # Record the "no dispatcher" outcome so Phase 8 still
        # learns about the failure mode (catches the regression
        # where a new action_type lands without its dispatcher).
        _record_outcome(
            action=action,
            success=False,
            error=(
                f"no executor registered for action_type="
                f"{action.action_type}"
            ),
        )
        return queue.attach_result(
            action_id,
            success=False,
            result={
                "error": (
                    f"no executor registered for action_type="
                    f"{action.action_type}"
                ),
            },
        )

    # W963-133: wrap dispatcher in active_store(action.
    # store_id) so its adapter calls (Shopify mutations,
    # LLM costs, etc.) resolve the right per-store
    # credentials. Pre-fix every approved-action
    # execution silently used env-default Shopify
    # credentials regardless of which store the action
    # was scoped to -- same money-class symptom W963-
    # 127/128 closed for cycle + webhook paths.
    sid = getattr(action, "store_id", None) or ""
    try:
        if sid:
            from core.context import active_store
            with active_store(sid):
                success, result = dispatcher(action.params)
        else:
            success, result = dispatcher(action.params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "dispatcher %s raised for %s: %s",
            action.action_type, action_id, exc,
        )
        success = False
        result = {"error": f"dispatcher_raised: {exc}"}

    # Phase 8: feed the autonomous learning loop with the queue-
    # path execution outcome. Direct-execute appliers already
    # call record_writeback themselves; this closes the parallel
    # gap for the queue path (PR follows #205/#206).
    _record_outcome(
        action=action,
        success=bool(success),
        error=(
            None if success
            else _extract_error(result)
        ),
    )

    return queue.attach_result(
        action_id,
        success=bool(success),
        result=result if isinstance(result, dict) else {},
    )


def _extract_error(result: Any) -> str | None:
    """Pull a readable error string out of the dispatcher
    result. Dispatchers return ``{"error": "..."}`` on failure;
    fall back to a string repr when the result shape is
    unexpected."""
    if isinstance(result, dict):
        err = result.get("error")
        if isinstance(err, str) and err:
            return err
        return "dispatcher_returned_failure"
    return "dispatcher_returned_failure"


def _record_outcome(
    *,
    action: ApprovalAction,
    success: bool,
    error: str | None,
) -> None:
    """Fan the queue-path execution outcome into Phase 8.

    Uses a lazy import so this module stays cheap. The recorder
    itself is Pattern-J-gated (short-circuits under
    ``PYTEST_CURRENT_TEST``) so test pollution isn't possible.
    Best-effort: a recorder import / call failure is logged and
    swallowed so it can never break the dispatch path.
    """
    try:
        from engines._writeback_recorder import record_writeback
        record_writeback(
            engine=action.engine,
            action_type=action.action_type,
            capability=action.capability,
            params=dict(action.params) if isinstance(action.params, dict) else {},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "executor recorder fan-out failed for %s: %s",
            action.id, exc,
        )


_dispatchers_loaded = False


def _ensure_dispatchers_loaded() -> None:
    """Lazy-import :mod:`core.approval.dispatchers` once.

    Keeps the module-load cost of ``core.approval`` minimal —
    importing ``dispatchers`` pulls in every engine applier
    helper, which transitively loads adapter capability tables
    and SmartRouter init paths.
    """
    global _dispatchers_loaded
    if _dispatchers_loaded:
        return
    try:
        from core.approval import dispatchers as _  # noqa: F401
        _dispatchers_loaded = True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dispatcher registry import failed: %s "
            "(execute_action will fall back to per-action error)",
            exc,
        )
