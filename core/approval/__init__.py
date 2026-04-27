"""Pre-execution approval queue.

The autonomous loop's writeback path (``engines/_writeback_recorder``)
records what *did* happen on Shopify. This package records what
*could* happen — engine recommendations parked for human review
before they touch the live store.

Public surface:
  * :class:`ApprovalQueue` — enqueue / list / approve / reject /
    record-result, SQLite-backed.
  * :func:`get_approval_queue` — process-wide singleton.
"""
from __future__ import annotations

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
    "get_approval_queue",
]
