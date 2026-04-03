"""Operations Agent executor — runs engines in sequence per plan.

Executor is the engine caller. Contains no logic.
Only runs engines specified in the plan in sequence.
Retries on failure with fallback.
"""
from __future__ import annotations

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
        engine_name = step["name"]
        engine_input = step["input"]

        # Enrich input with results from dependencies
        if step.get("depends_on"):
            engine_input = _enrich_from_dependencies(engine_input, step["depends_on"], engine_results)

        # Run engine with retry
        start = time.monotonic()
        result = _run_engine_with_retry(engine_name, engine_input)
        elapsed = time.monotonic() - start

        success = result.get("status") == "success"
        engine_results[engine_name] = result

        if success:
            completed += 1
        else:
            failed += 1

        step_details.append({
            "engine": engine_name,
            "success": success,
            "elapsed_seconds": round(elapsed, 3),
            "error": result.get("error") if not success else None,
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
    engine = _get_engine(engine_name)
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
            if result.get("status") == "success":
                return result
            last_error = result.get("error", {}).get("reason", "Unknown error")
        except Exception as exc:
            last_error = str(exc)

    return {
        "status": "fail",
        "data": None,
        "meta": {"engine": engine_name, "attempts": MAX_RETRIES + 1},
        "error": {"reason": f"Failed after {MAX_RETRIES + 1} attempts: {last_error}"},
    }


def _get_engine(engine_name: str) -> Any:
    """Load engine by name. Returns engine instance or None."""
    engine_map = {
        "inventory": "engines.inventory.InventoryEngine",
        "stock_prediction": "engines.stock_prediction.StockPredictionEngine",
        "supplier": "engines.supplier.SupplierEngine",
        "supplier_discovery": "engines.supplier_discovery.SupplierDiscoveryEngine",
        "shipping_optimization": "engines.shipping_optimization.ShippingOptimizationEngine",
        "returns_management": "engines.returns_management.ReturnsManagementEngine",
    }

    module_path = engine_map.get(engine_name)
    if not module_path:
        return None

    try:
        parts = module_path.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(parts[0])
        cls = getattr(mod, parts[1])
        return cls()
    except Exception:
        return None


def _enrich_from_dependencies(
    engine_input: dict[str, Any],
    dependencies: list[str],
    previous_results: dict[str, Any],
) -> dict[str, Any]:
    """Enrich engine input with results from previous engine runs.

    Example: Stock Prediction can use Inventory's current stock levels.
    """
    import copy
    enriched = copy.deepcopy(engine_input)
    data = enriched.get("data", {})

    for dep_name in dependencies:
        dep_result = previous_results.get(dep_name, {})
        if dep_result.get("status") != "success":
            continue

        dep_data = dep_result.get("data", {})

        # Inventory → Stock Prediction enrichment
        if dep_name == "inventory":
            if dep_data.get("inventory_health"):
                data["_inventory_health"] = dep_data["inventory_health"]
            if dep_data.get("stockout_risks"):
                data["_stockout_risks"] = dep_data["stockout_risks"]
            if dep_data.get("reorder_plan"):
                data["_reorder_plan"] = dep_data["reorder_plan"]

        # Supplier → Supplier Discovery enrichment
        if dep_name == "supplier":
            if dep_data.get("supplier_scores"):
                data["_supplier_scores"] = dep_data["supplier_scores"]

    enriched["data"] = data
    return enriched
