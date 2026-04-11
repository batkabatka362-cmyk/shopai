"""Workflow Builder Engine — validator.

Validates that a workflow is executable: no cycles, all engines exist, etc.
"""
from __future__ import annotations

from typing import Any

_KNOWN_ENGINES = {
    "inventory", "pricing", "market_simulator", "competitor_reaction_simulator",
    "cashflow_simulator", "customer_behavior_simulator", "campaign_strategy",
    "workflow_builder", "report_dashboard", "email_reporter",
    "product_selection", "product_scoring", "customer_segmentation",
    "forecasting", "demand_analysis", "competitor_analysis",
}


def validate_workflow(
    designed_steps: list[dict[str, Any]],
    dependency_graph: dict[str, Any],
) -> dict[str, Any]:
    """Validate the workflow for correctness."""
    try:
        errors: list[str] = []
        warnings: list[str] = []

        step_ids = [s.get("step_id", "") for s in designed_steps]
        ordered = dependency_graph.get("steps_ordered", [])

        # Check for cycles (ordered should contain all steps)
        if len(ordered) != len(step_ids):
            missing = set(step_ids) - set(ordered)
            errors.append(f"Circular dependency detected involving: {', '.join(missing)}")

        # Validate engines exist
        for step in designed_steps:
            engine = step.get("engine", "")
            if engine and engine not in _KNOWN_ENGINES:
                warnings.append(f"Engine '{engine}' not in known engine list — may not exist")

        # Check for empty workflow
        if not designed_steps:
            errors.append("Workflow has no steps")

        # Check for duplicate engines (warning only)
        engines = [s.get("engine", "") for s in designed_steps]
        seen = set()
        for e in engines:
            if e in seen:
                warnings.append(f"Engine '{e}' appears multiple times in workflow")
            seen.add(e)

        # Check dependencies reference valid steps/engines
        deps = dependency_graph.get("dependencies", {})
        for sid, dep_list in deps.items():
            for dep in dep_list:
                if dep not in step_ids:
                    errors.append(f"Step '{sid}' depends on unknown step '{dep}'")

        valid = len(errors) == 0

        return {
            "status": "success",
            "validation": {"valid": valid, "errors": errors, "warnings": warnings},
        }
    except Exception as exc:
        return {"status": "error", "validation": {}, "error": f"Validation failed: {exc}"}
