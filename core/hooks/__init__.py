"""Public surface for the hooks system.

Re-exports the dispatcher API so callers write
``from core.hooks import register`` instead of poking
into the submodule.

Lifecycle events emitted by ShopAI internals:

  * ``approval.queued``   — new pending action enqueued
  * ``approval.approved`` — merchant approved
  * ``approval.rejected`` — merchant rejected
  * ``approval.executed`` — approved action ran successfully
  * ``approval.failed``   — approved action ran and failed

Each event payload is ``{"name": str, "data": dict,
"timestamp": float}``; the ``data`` dict carries the action_id
plus engine / action_type / capability so the handler can
audit or route without re-reading the queue.
"""
from core.hooks.dispatcher import (
    clear,
    emit,
    register,
    registered_patterns,
    unregister,
)

__all__ = [
    "clear",
    "emit",
    "register",
    "registered_patterns",
    "unregister",
]
