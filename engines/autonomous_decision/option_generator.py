"""Autonomous Decision Engine — option generator.

Generate decision options by expanding provided options with
constraint-aware variants and scoring feasibility.
"""
from __future__ import annotations

import copy
from typing import Any


def generate_options(
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate and expand decision options.

    Args:
        **kwargs: Must include 'options' list and 'constraints' dict.

    Returns:
        Structured dict with expanded, scored options.
    """
    try:
        options = copy.deepcopy(kwargs.get("options", []))
        constraints = kwargs.get("constraints", {})
        context_data = kwargs.get("context_evaluator_data", {})
        complexity = context_data.get("complexity", "simple")

        scored_options: list[dict[str, Any]] = []

        for opt in options:
            if isinstance(opt, str):
                opt = {"id": opt, "label": opt, "params": {}}
            elif isinstance(opt, dict):
                opt.setdefault("id", str(opt.get("label", "unknown")))
            else:
                continue

            # Score feasibility against constraints
            violations = 0
            violation_details: list[str] = []
            for cname, cvalue in constraints.items():
                opt_val = opt.get("params", {}).get(cname)
                if opt_val is not None and isinstance(cvalue, (int, float)) and isinstance(opt_val, (int, float)):
                    if opt_val > cvalue:
                        violations += 1
                        violation_details.append(f"{cname}: {opt_val} > {cvalue}")

            feasibility = round(max(0.0, 1.0 - violations * 0.25), 2)
            opt["feasibility"] = feasibility
            opt["violations"] = violation_details
            opt["viable"] = feasibility >= 0.5
            scored_options.append(opt)

        # Sort by feasibility
        scored_options.sort(key=lambda o: o.get("feasibility", 0), reverse=True)
        viable_count = sum(1 for o in scored_options if o.get("viable"))

        return {
            "status": "success",
            "result": {
                "options": scored_options,
                "total": len(scored_options),
                "viable_count": viable_count,
                "complexity": complexity,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Option generation failed: {exc}"}
