"""Product Agent executor — runs engines in sequence per plan.

Executor is the engine caller. Contains no logic.
Only runs engines specified in the plan in sequence.
Retries on failure with fallback.
"""
from __future__ import annotations

import copy
import time
from typing import Any


# Max retry per engine
MAX_RETRIES = 2


def execute_plan(plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Execute all engines in the plan sequentially.

    Returns:
        {
            "engine_results": {engine_name: result},
            "completed_steps": int,
            "failed_steps": int,
            "step_details": [...],
        }
    """
    engine_results: dict[str, Any] = {}
    step_details: list[dict[str, Any]] = []
    completed = 0
    failed = 0

    for step in plan.get("engines", []):
        # Defensive: skip malformed step entries instead of
        # crashing the whole execution with KeyError. The
        # previous version did `step["name"]` direct access.
        if not isinstance(step, dict):
            continue
        engine_name = step.get("name")
        engine_input = step.get("input")
        if not engine_name:
            continue
        if not isinstance(engine_input, dict):
            engine_input = {}

        # Enrich input with results from dependencies
        if step.get("depends_on"):
            engine_input = _enrich_from_dependencies(engine_input, step["depends_on"], engine_results)

        # Run engine with retry
        start = time.monotonic()
        result = _run_engine_with_retry(engine_name, engine_input)
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
            "error": (result.get("error") if isinstance(result, dict) else None) if not success else None,
        })

    return {
        "engine_results": engine_results,
        "completed_steps": completed,
        "failed_steps": failed,
        "total_steps": len(plan.get("engines", [])),
        "step_details": step_details,
    }


def _run_engine_with_retry(engine_name: str, engine_input: dict[str, Any]) -> dict[str, Any]:
    """Run an engine with retry on failure."""
    from engines.registry import get_engine

    engine = get_engine(engine_name)
    if engine is None:
        return {
            "status": "fail",
            "data": None,
            "meta": {"engine": engine_name},
            "error": {"reason": f"Engine '{engine_name}' not found"},
        }

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = engine.run(engine_input)
            # Defensive: a buggy engine stub may return None
            # instead of a dict. Coerce to {} so the chained
            # .get() calls below can't crash with AttributeError.
            if not isinstance(result, dict):
                last_error = f"engine returned {type(result).__name__}"
                continue
            if result.get("status") == "success":
                return result
            # `dict.get(k, {})` only returns the default when the
            # key is MISSING — present-but-None error would crash
            # the chained .get(). `(... or {})` handles both.
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
        "error": {"reason": f"Failed after {MAX_RETRIES + 1} attempts: {last_error}"},
    }


def _enrich_from_dependencies(
    engine_input: dict[str, Any],
    dependencies: list[str],
    previous_results: dict[str, Any],
) -> dict[str, Any]:
    """Enrich engine input with results from previous engine runs.

    Example: Product ranking can use scoring results.
    """
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Product scoring → Product ranking enrichment
        if dep_name == "product_scoring":
            if dep_data.get("scored_products"):
                data["scored_products"] = dep_data["scored_products"]

        # Product filter → Pricing enrichment
        if dep_name == "product_filter":
            if dep_data.get("filtered_products"):
                data["products"] = dep_data["filtered_products"]

        # Pricing → Catalog enrichment
        if dep_name == "pricing":
            if dep_data.get("price_recommendations"):
                data["_price_recommendations"] = dep_data["price_recommendations"]

        # Pricing → Profitability enrichment
        if dep_name == "pricing":
            if dep_data.get("price_recommendations"):
                data["_pricing_data"] = dep_data["price_recommendations"]

    enriched["data"] = data
    return enriched
