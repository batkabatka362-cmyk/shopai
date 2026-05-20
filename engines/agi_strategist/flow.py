"""AGI Strategist Engine — Pattern Q wrapper.

Exposes the goal-decomposition pipeline as an engine with
the canonical ``run()`` envelope.

Input contract::

    {
      "goal": "Increase revenue 10% this quarter",   # required
      "horizon_days": 90,                              # optional
      "current_state": {"monthly_revenue": 42000},    # optional
      "constraints": ["no paid ads below 2.5 ROAS"],  # optional
    }

Output envelope (Pattern Q)::

    {
      "status": "success" | "error" | "fail",
      "data": {
        "goal", "horizon_days", "substrategies": [...],
        "confidence", "model_note",
      },
      "meta": {"engine": "agi_strategist"},
      "error": None | str,
    }

The engine never raises -- bad input -> ``status=error``
envelope with a structured ``error`` reason.
"""
from __future__ import annotations

from typing import Any

from .decomposer import decompose_goal


class AGIStrategistEngine:
    """Top-level goal-decomposition engine.

    Wraps :func:`decompose_goal` in the Pattern-Q canonical
    envelope so the autonomous controller can dispatch to it
    like any other engine.
    """

    name = "agi_strategist"

    def run(self, input_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run the strategist over the supplied input.

        Args:
            input_data: Dict carrying ``goal`` plus optional
                ``horizon_days`` / ``current_state`` /
                ``constraints``.

        Returns:
            Canonical engine envelope.
        """
        input_data = input_data or {}

        goal = input_data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            return {
                "status": "error",
                "data": {},
                "meta": {"engine": self.name},
                "error": "missing_or_empty_goal",
            }

        horizon_days_raw = input_data.get("horizon_days", 90)
        try:
            horizon_days = int(horizon_days_raw)
        except (TypeError, ValueError):
            horizon_days = 90
        horizon_days = max(1, min(365 * 2, horizon_days))

        current_state = input_data.get("current_state")
        if not isinstance(current_state, dict):
            current_state = {}

        constraints = input_data.get("constraints") or []
        if not isinstance(constraints, list):
            constraints = []
        constraints = [
            str(c).strip() for c in constraints
            if isinstance(c, (str, int, float)) and str(c).strip()
        ]

        return decompose_goal(
            goal=goal,
            horizon_days=horizon_days,
            current_state=current_state,
            constraints=constraints,
        )
