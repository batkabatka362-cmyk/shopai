"""Shared executor primitives for domain agents.

Audit pass 34 — extracted from the 7 byte-identical
``execute_plan`` / ``_run_engine_with_retry`` blocks that
existed in agents/{product,marketing,content,finance,
operations,customer,research}/executor.py.

Each domain executor only ever differed in its own
``_enrich_from_dependencies`` function. Everything else — the
defensive step-shape parsing, the retry loop, the shape of the
return dict, the timing wrapper — was duplicated 7 times,
which made every defensive bug fix in the audit series (passes
30-32) a 7-file copy/paste exercise.

This module gives the agents two entry points:

  * ``run_engine_with_retry(name, input)`` — the retry loop with
    all the defensive ``or {}`` / ``isinstance`` guards baked
    in. Routes through ``engines.registry.get_engine`` (Lego
    principle, enforced in pass 33).

  * ``execute_plan_base(plan, context, enrich_fn)`` — the
    full sequential plan runner. Domain executors pass their
    own ``enrich_fn`` so the cross-engine data wiring stays
    domain-specific while the boilerplate stays shared.

The thin wrapper each domain executor now exposes is just::

    def execute_plan(plan, context):
        return execute_plan_base(plan, context, _enrich_from_dependencies)
"""
from __future__ import annotations

import time
from typing import Any, Callable

# Max retry per engine. Identical across all 7 original
# executors; centralised here so a future tuning pass changes
# one constant instead of seven.
MAX_RETRIES = 2

EnrichFn = Callable[
    [dict[str, Any], list[str], dict[str, Any]],
    dict[str, Any],
]


def run_engine_with_retry(
    engine_name: str,
    engine_input: dict[str, Any],
) -> dict[str, Any]:
    """Run an engine via the global registry with retry on failure.

    Always returns a dict in the agent result contract:
        {"status": "success"|"fail", "data": ..., "meta": ..., "error": ...}

    Defensive guarantees (regression tests in
    ``tests/test_domain_agent_executors_audit.py``):
      • engine module fails to import → returns "Engine not found"
      • ``engine.run`` returns None / non-dict → counted as failure
      • ``engine.run`` returns ``{"error": None}`` → does not crash
        the chained ``.get("reason")``
      • ``engine.run`` returns ``{"error": "raw string"}`` → does
        not crash; the string becomes ``last_error``
      • ``engine.run`` raises → exception type + message captured
    """
    # Local import keeps the registry monkey-patchable per-test
    # (the audit test suite swaps ``engines.registry.get_engine``
    # via monkeypatch).
    from engines.registry import get_engine

    engine = get_engine(engine_name)
    if engine is None:
        return {
            "status": "fail",
            "data": None,
            "meta": {"engine": engine_name},
            "error": {"reason": f"Engine '{engine_name}' not found"},
        }

    last_error: str | None = None
    for _attempt in range(MAX_RETRIES + 1):
        try:
            result = engine.run(engine_input)
            # Defensive: a buggy engine stub may return None
            # instead of a dict. Coerce so the chained .get()
            # calls below can't crash with AttributeError.
            if not isinstance(result, dict):
                last_error = f"engine returned {type(result).__name__}"
                continue
            if result.get("status") == "success":
                return result
            # ``dict.get(k, {})`` only returns the default when
            # the key is MISSING — present-but-None error would
            # crash the chained .get(). ``(... or {})`` handles
            # both.
            err_obj = result.get("error") or {}
            if isinstance(err_obj, dict):
                last_error = err_obj.get("reason", "Unknown error")
            else:
                last_error = str(err_obj)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"

    return {
        "status": "fail",
        "data": None,
        "meta": {"engine": engine_name, "attempts": MAX_RETRIES + 1},
        "error": {
            "reason": f"Failed after {MAX_RETRIES + 1} attempts: {last_error}"
        },
    }


def execute_plan_base(
    plan: dict[str, Any],
    context: dict[str, Any],  # noqa: ARG001 — kept for parity with the
    # per-agent contract; future enrichment functions may need it.
    enrich_fn: EnrichFn,
) -> dict[str, Any]:
    """Execute every engine in the plan sequentially.

    Args:
        plan: ``{"engines": [{"name": str, "input": dict,
            "depends_on": [str]}, ...]}`` — malformed step
            entries are skipped, not raised on.
        context: agent context (currently unused by the base
            runner; passed through for future hooks and to keep
            every domain executor's signature uniform).
        enrich_fn: agent-specific enrichment that copies fields
            from already-completed dependency results into the
            current step's input. The base runner only invokes
            it when ``step["depends_on"]`` is truthy.

    Returns:
        ``{
            "engine_results": {engine_name: result},
            "completed_steps": int,
            "failed_steps": int,
            "total_steps": int,
            "step_details": [...],
        }``
    """
    engine_results: dict[str, Any] = {}
    step_details: list[dict[str, Any]] = []
    completed = 0
    failed = 0

    raw_steps = plan.get("engines", []) if isinstance(plan, dict) else []
    if not isinstance(raw_steps, list):
        raw_steps = []

    for step in raw_steps:
        # Defensive: skip malformed step entries instead of
        # crashing the whole execution with KeyError. Original
        # bug (audit pass 32) was direct ``step["name"]``
        # access.
        if not isinstance(step, dict):
            continue
        engine_name = step.get("name")
        engine_input = step.get("input")
        if not engine_name:
            continue
        if not isinstance(engine_input, dict):
            engine_input = {}

        # Enrich input with results from dependencies. The
        # depends_on list is agent-specific knowledge, so the
        # caller-supplied enrich_fn drives the wiring.
        depends_on = step.get("depends_on")
        if depends_on:
            try:
                engine_input = enrich_fn(engine_input, depends_on, engine_results)
            except Exception as exc:  # noqa: BLE001
                # A buggy enrichment function should not crash
                # the entire plan. Mark this step as failed and
                # continue with the next.
                failed += 1
                step_details.append({
                    "engine": engine_name,
                    "success": False,
                    "elapsed_seconds": 0.0,
                    "error": {
                        "reason": (
                            f"enrichment failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    },
                })
                continue

        start = time.monotonic()
        result = run_engine_with_retry(engine_name, engine_input)
        elapsed = time.monotonic() - start

        success = isinstance(result, dict) and result.get("status") == "success"
        engine_results[engine_name] = result if isinstance(result, dict) else {}

        if success:
            completed += 1
        else:
            failed += 1

        step_details.append({
            "engine": engine_name,
            "success": success,
            "elapsed_seconds": round(elapsed, 3),
            "error": (
                (result.get("error") if isinstance(result, dict) else None)
                if not success
                else None
            ),
        })

    return {
        "engine_results": engine_results,
        "completed_steps": completed,
        "failed_steps": failed,
        "total_steps": len(raw_steps),
        "step_details": step_details,
    }
