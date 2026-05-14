"""Engine completion emit — attach hook fan-out to ``engine.run``.

After PR #88's hooks dispatcher landed, the approval-queue
lifecycle gained five named events. This module extends the
same substrate to engine completions, emitting two events per
successful engine run:

  * ``engine.<name>.completed`` — per-engine pattern; lets a
    handler subscribe to one specific engine's runs without
    filtering globally.
  * ``engine.completed``        — global; every engine fans in
    here, useful for telemetry / audit-log style consumers.

Both fire on success AND on error (the engine's contract is to
NEVER raise — it returns a structured output dict whose
``status`` field tells the caller what happened). Crash-style
raises are also captured: if the underlying ``run`` raises an
exception, the emitter fires with ``status="error"`` and the
exception's message in the payload, then re-raises so the
caller still sees the crash.

Wiring strategy
---------------
``attach_completion_emitter(engine, engine_name)`` monkey-patches
the ``run`` method on the instance with a wrapping closure.
Patching the method (not wrapping the whole object) preserves
``engine.__class__`` / ``engine.engine_name`` /
``required_input_fields`` etc. for callers like
``/api/engines/<name>`` that introspect the engine.

The patch is idempotent — re-attaching to the same instance
no-ops via a sentinel attribute, so a re-registered engine
doesn't double-emit.

Used by ``engines/registry.py::get_engine``; every engine resolved
through the registry gets emit for free. Direct instantiation
(``CartRecoveryEngine().run(...)``) bypasses — that's intentional
for test isolation (the hooks layer also has its
``PYTEST_CURRENT_TEST`` guard for the same reason).
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger

logger = get_logger("core.hooks.engine_emitter")


_PATCHED_FLAG = "_shopai_completion_emit_attached"


def attach_completion_emitter(engine: Any, engine_name: str) -> Any:
    """Patch ``engine.run`` to emit completion hooks.

    Returns the engine unchanged (in-place modification) so the
    caller can keep using the same object. Idempotent — calling
    twice on the same instance leaves it patched exactly once.

    Args:
        engine: Engine instance with a callable ``run`` attribute.
        engine_name: Canonical engine name (used in the event
            name and payload). Should match what the registry
            keys this engine under.

    Returns:
        The same engine, with ``run`` decorated.
    """
    if engine is None:
        return engine
    if getattr(engine, _PATCHED_FLAG, False):
        return engine
    original_run = getattr(engine, "run", None)
    if not callable(original_run):
        # Engine doesn't have a callable ``run`` — nothing to wrap.
        # Could happen during test stubs; silently skip.
        return engine

    def _wrapped_run(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        error: BaseException | None = None
        output: Any = None
        try:
            output = original_run(*args, **kwargs)
            return output
        except BaseException as exc:  # noqa: BLE001
            error = exc
            raise
        finally:
            try:
                _emit(
                    engine_name=engine_name,
                    output=output,
                    elapsed=time.monotonic() - start,
                    error=error,
                )
            except Exception as emit_exc:  # noqa: BLE001
                # Hook emission must never propagate. The
                # underlying run() result (or exception) is
                # the source of truth; we just couldn't tell
                # listeners. Log + carry on.
                logger.debug(
                    "completion-emit raised for %s: %s",
                    engine_name, emit_exc,
                )

    # Bind the wrapped function as the new run method.
    # Using setattr (not __set_name__ / descriptor magic) so the
    # engine's class definition is untouched — only this instance
    # is decorated.
    try:
        setattr(engine, "run", _wrapped_run)
    except Exception as exc:  # noqa: BLE001
        # Slot-based / immutable classes can't have attributes
        # rebound. Surface in debug log and leave the engine as-is
        # (consumer keeps the un-decorated run; degrades to
        # "no completion event" which is the pre-fix state).
        logger.debug(
            "completion-emit attach failed for %s: %s",
            engine_name, exc,
        )
        return engine

    try:
        setattr(engine, _PATCHED_FLAG, True)
    except Exception:  # noqa: BLE001
        pass
    return engine


# ── Internals ─────────────────────────────────────────────────


def _emit(
    *,
    engine_name: str,
    output: Any,
    elapsed: float,
    error: BaseException | None,
) -> None:
    """Build the event payload and fire both pattern variants.

    Payload shape:

        {
          "engine":           <engine name>,
          "status":           "success" | "error",
          "elapsed_seconds":  <float, rounded to 4dp>,
          "output_status":    <str from output.status, when present>,
          "error":            <str, only when status == error>,
        }

    Two events fire: ``engine.<name>.completed`` followed by the
    global ``engine.completed`` — same payload, different patterns.
    A handler registered for the per-engine name only sees its own
    engine; a global ``engine.completed`` handler sees every
    completion. (Note: the dispatcher's ``engine.*`` wildcard also
    catches the per-engine event — this module fires the global
    name explicitly anyway so a handler registered on the literal
    ``"engine.completed"`` exact name still receives every run.)
    """
    try:
        from core.hooks import emit
    except Exception as exc:  # noqa: BLE001
        logger.debug("hooks import failed in engine emitter: %s", exc)
        return

    status = _resolve_status(output, error)
    output_status = _output_status(output)

    payload: dict[str, Any] = {
        "engine": engine_name,
        "status": status,
        "elapsed_seconds": round(float(elapsed), 4),
    }
    if output_status is not None:
        payload["output_status"] = output_status
    if error is not None:
        payload["error"] = f"{type(error).__name__}: {error}"
    elif isinstance(output, dict):
        # Engine returned a structured error in its output — copy
        # the message through without overriding the crash form.
        err_field = output.get("error")
        if err_field:
            payload["error"] = str(err_field)

    emit(f"engine.{engine_name}.completed", payload)
    emit("engine.completed", payload)


def _resolve_status(
    output: Any, error: BaseException | None,
) -> str:
    """Map (output, exception) → ``"success"`` | ``"error"``.

    * A raised exception is always ``"error"``.
    * Otherwise, peek at ``output["status"]`` — engines use
      ``"success"`` / ``"error"`` / ``"fail"`` / ``"completed"``;
      anything not explicitly success-like maps to error.
    * Absent ``output["status"]`` falls back to ``"success"`` —
      the engine returned without raising, so there's no signal
      to mark it failed.
    """
    if error is not None:
        return "error"
    if isinstance(output, dict):
        raw = str(output.get("status", "success")).lower()
        if raw in ("success", "ok", "completed"):
            return "success"
        if raw in ("error", "fail", "failed"):
            return "error"
        # Unknown status string — be conservative, treat as error.
        return "error"
    return "success"


def _output_status(output: Any) -> str | None:
    """Surface the raw output.status string for handlers that
    want it (telemetry consumers, audit logs). Returns ``None``
    when the output isn't a dict or has no status field."""
    if isinstance(output, dict):
        raw = output.get("status")
        if isinstance(raw, str):
            return raw
    return None
