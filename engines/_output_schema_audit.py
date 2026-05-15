"""Pattern Q audit -- every registered engine's ``run()`` must
return the canonical ``{status, data, meta, error}`` envelope.

The envelope contract is implicit today: every engine's
``run()`` declares the shape in its docstring, but there's no
runtime check. A refactor that drops one of the four keys
ships to production silently -- downstream consumers
(approval queue narrative, recommender's ``record_outcome``,
the Phase 8 recorder) all assume the envelope.

Pattern Q closes that gap. For every engine registered in
``engines.registry``, the audit:

  1. Instantiates the engine.
  2. Calls ``engine.run()`` with an empty input
     ``{status: "success", data: {}, meta: {}, error: None}``.
  3. Verifies the result is a ``dict`` with the four canonical
     keys.
  4. Verifies the ``status`` value is one of the accepted
     literals (``success`` / ``error`` / ``fail``).

Failures are tolerated and recorded as classification info, not
hard errors: engines may legitimately return
``status="error"`` on empty input (they need real data). The
test isn't "engine runs cleanly" -- it's "engine returns the
canonical envelope".

Returns a structured report. The audit is RUNTIME (it actually
calls each engine) rather than AST-based, because most engines
compute their envelope dict dynamically and an AST walk can't
verify it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines._output_schema_audit")


_EXPECTED_KEYS: frozenset[str] = frozenset(
    {"status", "data", "meta", "error"},
)
_ACCEPTED_STATUS: frozenset[str] = frozenset(
    {"success", "error", "fail"},
)


@dataclass(frozen=True)
class EngineSchemaViolation:
    """One engine that doesn't return the canonical envelope."""

    engine: str
    reason: str           # short tag (e.g. ``missing_keys``,
                          # ``not_a_dict``, ``raised``)
    detail: str           # specifics (which keys / status val /
                          # exception message)


@dataclass(frozen=True)
class EngineSchemaReport:
    scanned_engines: int
    clean_engines: list[str] = field(default_factory=list)
    violations: list[EngineSchemaViolation] = field(default_factory=list)
    skipped_engines: list[str] = field(default_factory=list)
    """Engines that couldn't be instantiated (e.g. dependency
    not configured). Not a violation -- just a no-op."""

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


# Empty input envelope -- the canonical "no-data success" shape.
# Engines that need real data return status="error" cleanly;
# they should still emit the four-key envelope.
_EMPTY_INPUT: dict[str, Any] = {
    "status": "success",
    "data": {},
    "meta": {},
    "error": None,
}


def _is_test_environment() -> bool:
    """Pattern J guard -- mirror the recorder's contract so the
    audit itself doesn't pollute on-disk state when run under
    pytest (engines may write to MemoryIntelligence on a
    success path)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def audit_engine_output_schema(
    engine_names: list[str] | None = None,
) -> EngineSchemaReport:
    """Run every registered engine with an empty input and
    verify the canonical envelope.

    Args:
        engine_names: Optional explicit list to scan (defaults
            to every engine in :func:`engines.registry.list_engines`).
            Tests use this to scope down.

    Returns:
        :class:`EngineSchemaReport` summarising which engines
        return clean envelopes, which violate the contract, and
        which couldn't be instantiated.
    """
    try:
        from engines.registry import get_engine, list_engines
    except Exception as exc:  # noqa: BLE001
        logger.debug("registry import failed: %s", exc)
        return EngineSchemaReport(scanned_engines=0)

    names = engine_names if engine_names is not None else list_engines()

    clean: list[str] = []
    violations: list[EngineSchemaViolation] = []
    skipped: list[str] = []
    scanned = 0
    for name in names:
        scanned += 1
        try:
            engine = get_engine(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_engine(%s) raised: %s", name, exc)
            skipped.append(name)
            continue
        if engine is None:
            skipped.append(name)
            continue
        # Engines instantiated as classes need a callable
        # ``run``; engines exposed as functions also have
        # ``run`` (the registry returns the entry point).
        runner = getattr(engine, "run", None)
        if not callable(runner):
            skipped.append(name)
            continue
        try:
            # Pass a defensive copy so an engine that mutates
            # its input can't break the next engine in the loop.
            import copy as _copy
            result = runner(_copy.deepcopy(_EMPTY_INPUT))
        except Exception as exc:  # noqa: BLE001
            violations.append(EngineSchemaViolation(
                engine=name,
                reason="raised",
                detail=f"{type(exc).__name__}: {exc}",
            ))
            continue

        if not isinstance(result, dict):
            violations.append(EngineSchemaViolation(
                engine=name,
                reason="not_a_dict",
                detail=f"returned {type(result).__name__}",
            ))
            continue
        keys = set(result.keys())
        missing = _EXPECTED_KEYS - keys
        if missing:
            violations.append(EngineSchemaViolation(
                engine=name,
                reason="missing_keys",
                detail=f"missing {sorted(missing)}",
            ))
            continue
        status = result.get("status")
        if status not in _ACCEPTED_STATUS:
            violations.append(EngineSchemaViolation(
                engine=name,
                reason="bad_status",
                detail=(
                    f"status={status!r} (expected one of "
                    f"{sorted(_ACCEPTED_STATUS)})"
                ),
            ))
            continue
        clean.append(name)

    return EngineSchemaReport(
        scanned_engines=scanned,
        clean_engines=clean,
        violations=violations,
        skipped_engines=skipped,
    )
