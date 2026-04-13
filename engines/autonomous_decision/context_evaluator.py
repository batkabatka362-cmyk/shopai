"""Autonomous Decision Engine — context evaluator.

Evaluate current context/state to understand the decision environment.
Scores context completeness, identifies missing information, and
classifies the decision scenario.
"""
from __future__ import annotations

import copy
from typing import Any


def evaluate_context(
    **kwargs: Any,
) -> dict[str, Any]:
    """Evaluate current context for decision-making.

    Args:
        **kwargs: Must include 'context' dict and 'goal' str.

    Returns:
        Structured dict with context evaluation results.
    """
    try:
        context = copy.deepcopy(kwargs.get("context", {}))
        goal = str(kwargs.get("goal", ""))

        # Assess context completeness
        total_fields = len(context)
        non_empty = sum(1 for v in context.values() if v)
        completeness = round(non_empty / max(total_fields, 1), 2)

        # Identify missing or weak signals
        missing: list[str] = []
        for k, v in context.items():
            if v is None or v == "" or v == [] or v == {}:
                missing.append(k)

        # Classify scenario urgency
        urgency = "low"
        if context.get("time_pressure"):
            urgency = "high"
        elif context.get("deadline"):
            urgency = "medium"

        # Determine decision complexity
        constraints = kwargs.get("constraints", {})
        options = kwargs.get("options", [])
        complexity = "simple"
        if len(options) > 5 or len(constraints) > 3:
            complexity = "complex"
        elif len(options) > 2 or len(constraints) > 1:
            complexity = "moderate"

        return {
            "status": "success",
            "result": {
                "completeness": completeness,
                "missing_fields": missing,
                "urgency": urgency,
                "complexity": complexity,
                "context_fields": total_fields,
                "goal": goal,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Context evaluation failed: {exc}"}
