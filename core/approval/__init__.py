"""Pre-execution approval queue + executor.

The autonomous loop's writeback path (``engines/_writeback_recorder``)
records what *did* happen on Shopify. This package records what
*could* happen — engine recommendations parked for human review
before they touch the live store, and the executor that replays
APPROVED actions through their original engine appliers.

Public surface:
  * :class:`ApprovalQueue` — enqueue / list / approve / reject /
    attach-result, SQLite-backed.
  * :func:`get_approval_queue` — process-wide singleton.
  * :func:`execute_action` — replay an APPROVED action through
    its registered dispatcher; flips status to EXECUTED / FAILED.
  * :func:`list_registered_action_types` — snapshot of action_types
    the executor can dispatch.

Importing this package also attaches the brain-stack's goal
feedback handlers (``core.goals.goal_feedback``) to the
queue's lifecycle hooks. Before this, the feedback loop was
opt-in via an explicit ``register_goal_feedback()`` call that
no production code path made — the entire EMA-update edge of
the brain stack was dormant in real deployments. The hooks
dispatcher's pytest gate (PR #54) means auto-attach is now
safe in test environments.
"""
from __future__ import annotations

from utils.logger import get_logger

from core.approval.executor import (
    execute_action,
    list_registered_action_types,
)
from core.approval.queue import (
    ApprovalAction,
    ApprovalQueue,
    ApprovalStatus,
    get_approval_queue,
)

_logger = get_logger("core.approval")


def _auto_register_goal_feedback() -> None:
    """Best-effort wiring of the goal-feedback handlers.

    Called once on package import. Any failure (goals module
    broken, hooks dispatcher unavailable, etc.) is logged at
    debug level — the approval queue itself stays fully usable
    even if the brain-stack edge can't attach.
    """
    try:
        from core.goals.goal_feedback import register_goal_feedback
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "goal_feedback import failed; brain-stack edge "
            "stays dormant: %s", exc,
        )
        return
    try:
        register_goal_feedback()
    except Exception as exc:  # noqa: BLE001
        _logger.debug(
            "goal_feedback registration raised: %s", exc,
        )


_auto_register_goal_feedback()


__all__ = [
    "ApprovalAction",
    "ApprovalQueue",
    "ApprovalStatus",
    "execute_action",
    "get_approval_queue",
    "list_registered_action_types",
]
