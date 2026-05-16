"""Active-store thread-local context.

The autonomous loop iterates over stores. When it invokes an
engine for store X, every action the engine enqueues OR writes
back should carry ``store_id=X`` so the per-store filter
(PR #239) actually works in production.

Threading ``store_id`` through every engine's call signature
would touch ~50 engines for very little new code. Instead, this
module exposes a thread-local "active store" that the
autonomous loop sets once per iteration:

    with active_store("store-a"):
        engine.run(input_data)
        # any enqueue / record_writeback inside picks up
        # store_id="store-a" automatically

Engines that want explicit control can still pass
``store_id=...`` to ``ApprovalQueue.enqueue`` and the explicit
value wins. The context fallback is opt-in for the queue and
recorder layers; engines themselves don't need to know it
exists.

Resilience: if no context is set, ``get_active_store_id()``
returns None (matches the pre-PR-#239 behaviour where store_id
was always NULL).
"""
from __future__ import annotations

import contextlib
import threading
from typing import Iterator

_local = threading.local()


def get_active_store_id() -> str | None:
    """Return the currently active store, or None.

    Safe to call from any thread; falls back to None when no
    context is set. Designed for callers that want to default
    a ``store_id`` parameter without crashing when the autonomous
    loop hasn't set one.
    """
    return getattr(_local, "store_id", None)


def set_active_store_id(store_id: str | None) -> None:
    """Explicitly set / clear the active store on this thread.

    Most callers should use :func:`active_store` (the context
    manager). This setter exists for the autonomous loop's
    boundaries where a context manager is awkward (e.g. async
    callback handlers that need to set + clear at separate
    points).
    """
    _local.store_id = store_id


@contextlib.contextmanager
def active_store(store_id: str | None) -> Iterator[None]:
    """Run a block with the active store set on this thread.

    Restores the previous value on exit (nested contexts are
    safe). Pass ``None`` to explicitly clear within a block.

    Example::

        with active_store("store-a"):
            engine.run(input_data)
        # outside the block, get_active_store_id() == previous

    Per-thread: concurrent calls in different threads each see
    their own active store. ``threading.local`` guarantees this.
    """
    previous = getattr(_local, "store_id", None)
    _local.store_id = store_id
    try:
        yield
    finally:
        _local.store_id = previous
