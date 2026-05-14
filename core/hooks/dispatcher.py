"""Event-hook dispatcher — register callbacks for named lifecycle events.

The hooks layer lets merchants (and ShopAI's own internal systems)
react to lifecycle events without modifying engine or queue code.
The first wave of named events comes from the approval queue:

  * ``approval.queued``   — a new pending action just landed
  * ``approval.approved`` — merchant approved an action
  * ``approval.rejected`` — merchant rejected an action
  * ``approval.executed`` — approved action ran successfully
  * ``approval.failed``   — approved action ran and failed

The same dispatcher is the substrate for engine-completion events
and writeback notifications in follow-up PRs.

Design
------

* **Synchronous fan-out.** Handlers run inline when ``emit`` is
  called. Simpler than async and the approval lifecycle already
  serialises through a single SQLite write lock — adding an
  async layer here would just push the synchronisation cost
  somewhere less obvious.
* **Failures isolated.** One handler raising doesn't break the
  emit call or stop other handlers from running. Exceptions are
  logged and the emit returns the count of successful + failed
  handlers so callers can audit.
* **Wildcards via dotted-prefix match.** ``register("approval.*",
  fn)`` catches every event whose name starts with ``approval.``;
  ``register("*", fn)`` catches everything. Exact-name matches
  always win (run alongside wildcards in registration order).
* **Test-mode bypass.** Like ``_writeback_recorder``, the
  dispatcher short-circuits to a no-op when
  ``PYTEST_CURRENT_TEST`` is set — except inside the hooks
  test file itself, which exercises the bypass via the autouse
  ``_disable_test_env_guard`` fixture pattern (same convention
  as the writeback recorder tests).

Usage
-----

Decorator:

    from core.hooks import register

    @register("approval.queued")
    def notify_slack(event):
        # event: {"name": str, "data": dict, "timestamp": float}
        send_slack(f"Approval queued: {event['data']['action_id']}")

Programmatic:

    from core.hooks import register, emit, unregister

    def my_handler(event): ...
    register("approval.*", my_handler)

    emit("approval.queued", {"action_id": "appr_..."})

    unregister("approval.*", my_handler)

Wildcard semantics:

    register("*", fn)             # every event
    register("approval.*", fn)    # approval.queued, .approved, ...
    register("approval.queued", fn)  # exact

When an event fires, every handler whose pattern matches the event
name runs — exact + wildcards both fire. Handler order within a
pattern is registration order.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Any, Callable

from utils.logger import get_logger

logger = get_logger("core.hooks")


HookCallable = Callable[[dict[str, Any]], None]


_LOCK = threading.RLock()
# pattern → list of handler callables. Insertion order preserved.
_HANDLERS: dict[str, list[HookCallable]] = defaultdict(list)


def _is_test_environment() -> bool:
    """Mirror the ``_writeback_recorder`` guard pattern.

    Tests inadvertently exercising the hooks code path shouldn't
    fan out to real handlers (which may write to external systems
    in production). Tests that DO want hook behaviour install an
    autouse fixture that patches this function to return False.
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def register(pattern: str, handler: HookCallable | None = None):
    """Register ``handler`` for events matching ``pattern``.

    Two call shapes:

    Decorator (one-shot):

        @register("approval.queued")
        def my_handler(event): ...

    Programmatic:

        register("approval.*", my_handler)

    Returns the handler unchanged so the decorator form preserves
    the wrapped function.
    """
    def _do_register(fn: HookCallable) -> HookCallable:
        if not callable(fn):
            raise TypeError(
                f"hook handler must be callable, got {type(fn).__name__}",
            )
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("hook pattern must be a non-empty string")
        with _LOCK:
            _HANDLERS[pattern.strip()].append(fn)
        logger.debug(
            "hook registered: pattern=%r handler=%s",
            pattern, getattr(fn, "__qualname__", repr(fn)),
        )
        return fn

    if handler is None:
        # Decorator form: @register("approval.queued")
        return _do_register
    # Programmatic form: register("approval.queued", fn)
    return _do_register(handler)


def unregister(pattern: str, handler: HookCallable) -> bool:
    """Remove ``handler`` from ``pattern``. Returns True if the
    handler was registered and got removed; False if it wasn't
    on file (idempotent).
    """
    if not isinstance(pattern, str):
        return False
    with _LOCK:
        bucket = _HANDLERS.get(pattern.strip(), [])
        try:
            bucket.remove(handler)
        except ValueError:
            return False
        if not bucket:
            _HANDLERS.pop(pattern.strip(), None)
        return True


def clear() -> None:
    """Drop every registered handler. Primarily for tests that
    need a clean slate per-case.
    """
    with _LOCK:
        _HANDLERS.clear()


def emit(name: str, data: dict[str, Any] | None = None) -> dict[str, int]:
    """Fan out a named event to every matching handler.

    Returns ``{"fired": int, "failed": int}`` so the caller can
    audit how many handlers ran successfully.

    Synchronous: handlers run inline in registration order, exact
    matches first then wildcards. One handler raising doesn't
    stop the fan-out — exceptions are logged and counted as
    ``failed``.

    Under pytest, the dispatcher short-circuits to ``{"fired": 0,
    "failed": 0}`` so the test suite doesn't accidentally fire
    real handlers wired into production telemetry / notification
    sinks. Tests that need hooks behaviour patch
    ``_is_test_environment`` to return False.
    """
    if _is_test_environment():
        return {"fired": 0, "failed": 0}

    if not isinstance(name, str) or not name.strip():
        return {"fired": 0, "failed": 0}
    safe_name = name.strip()

    event: dict[str, Any] = {
        "name": safe_name,
        "data": dict(data) if isinstance(data, dict) else {},
        "timestamp": time.time(),
    }

    handlers = _resolve_handlers(safe_name)
    if not handlers:
        return {"fired": 0, "failed": 0}

    fired = 0
    failed = 0
    for fn in handlers:
        try:
            fn(event)
            fired += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning(
                "hook handler raised for event %s: %s (%s)",
                safe_name,
                getattr(fn, "__qualname__", repr(fn)),
                exc,
            )
    return {"fired": fired, "failed": failed}


def registered_patterns() -> dict[str, int]:
    """Snapshot ``{pattern → handler count}``. Inspection-only.

    The API surface and tests use this to see what's wired without
    exposing the handler list itself.
    """
    with _LOCK:
        return {p: len(h) for p, h in _HANDLERS.items() if h}


def _resolve_handlers(event_name: str) -> list[HookCallable]:
    """Walk the registry and return every handler whose pattern
    matches ``event_name``.

    Match rules:
      * Exact: pattern == event_name.
      * Wildcard ``*``: catches every event.
      * Dotted-prefix wildcard ``foo.*``: matches every event
        whose name starts with ``foo.``.

    Exact matches are returned first so deterministic-order
    handlers can rely on running before any wildcard handler.
    """
    exact: list[HookCallable] = []
    wildcards: list[HookCallable] = []
    with _LOCK:
        for pattern, bucket in _HANDLERS.items():
            if pattern == event_name:
                exact.extend(bucket)
            elif pattern == "*":
                wildcards.extend(bucket)
            elif pattern.endswith(".*"):
                prefix = pattern[:-1]  # keep the trailing dot
                if event_name.startswith(prefix):
                    wildcards.extend(bucket)
    return exact + wildcards
