"""Workflow Builder Engine — step designer.

Designs workflow steps from available engines, assigns IDs and estimates durations.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any

# Average engine run durations (seconds) — estimates
_ENGINE_DURATIONS = {
    "inventory": 2.5,
    "pricing": 1.8,
    "market_simulator": 3.0,
    "competitor_reaction_simulator": 2.0,
    "cashflow_simulator": 1.5,
    "customer_behavior_simulator": 2.2,
    "campaign_strategy": 1.8,
    "report_dashboard": 2.0,
    "email_reporter": 1.0,
}


def design_steps(
    steps: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Design workflow steps with IDs and duration estimates."""
    try:
        steps = copy.deepcopy(steps)
        designed: list[dict[str, Any]] = []

        for i, step in enumerate(steps):
            engine = str(step.get("engine", ""))
            config = step.get("config", {})
            depends_on = step.get("depends_on", [])

            step_id = f"step_{i + 1}_{engine}" if engine else f"step_{i + 1}_{uuid.uuid4().hex[:6]}"
            duration = _ENGINE_DURATIONS.get(engine, 2.0)

            designed.append({
                "step_id": step_id,
                "engine": engine,
                "config": config,
                "depends_on": depends_on,
                "estimated_duration_seconds": duration,
            })

        return {"status": "success", "designed_steps": designed}
    except Exception as exc:
        return {"status": "error", "designed_steps": [], "error": f"Step design failed: {exc}"}
