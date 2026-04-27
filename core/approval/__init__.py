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
"""
from __future__ import annotations

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

__all__ = [
    "ApprovalAction",
    "ApprovalQueue",
    "ApprovalStatus",
    "execute_action",
    "get_approval_queue",
    "list_registered_action_types",
]
