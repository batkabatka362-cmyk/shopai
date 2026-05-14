"""Public surface for the hooks system.

Re-exports the dispatcher API so callers write
``from core.hooks import register`` instead of poking
into the submodule.

Lifecycle events emitted by ShopAI internals:

  Approval queue (PR #88):
  * ``approval.queued``   — new pending action enqueued
  * ``approval.approved`` — merchant approved
  * ``approval.rejected`` — merchant rejected
  * ``approval.executed`` — approved action ran successfully
  * ``approval.failed``   — approved action ran and failed

  Engine completion (attached at the registry layer):
  * ``engine.<name>.completed`` — fires after each ``engine.run``
    (per-engine pattern; one event per registered engine name)
  * ``engine.completed``        — same payload, global pattern

Each event payload is ``{"name": str, "data": dict,
"timestamp": float}``; the ``data`` dict carries action / engine
metadata so the handler can audit or route without re-reading
the source-of-truth state.
"""
from core.hooks.dispatcher import (
    clear,
    emit,
    register,
    registered_patterns,
    unregister,
)
from core.hooks.engine_emitter import attach_completion_emitter

__all__ = [
    "attach_completion_emitter",
    "clear",
    "emit",
    "register",
    "registered_patterns",
    "unregister",
]
