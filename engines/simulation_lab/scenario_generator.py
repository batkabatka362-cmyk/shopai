"""Simulation Lab — scenario generator.

Generates test scenarios from input parameters: baseline, aggressive,
conservative, edge-case, and alternative variations.

Model note: Would use LLaMA for creative scenario synthesis.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


def generate_scenarios(
    strategy_type: str,
    base_parameters: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    num_scenarios: int = 5,
) -> dict[str, Any]:
    """Generate a diverse set of test scenarios.

    Produces a baseline plus variations that stress-test different aspects
    of the strategy space.

    Args:
        strategy_type: e.g. "pricing", "inventory", "marketing".
        base_parameters: The starting parameter set.
        constraints: Hard limits the scenarios must respect.
        objectives: What to optimize for.
        num_scenarios: Total number of scenarios to produce.

    Returns:
        Structured dict with list of Scenario dicts.
    """
    try:
        params = copy.deepcopy(base_parameters)
        cons = copy.deepcopy(constraints)

        scenarios: list[dict[str, Any]] = []

        # Always include a baseline
        scenarios.append(_build_scenario(
            label="Baseline",
            description="Unmodified base parameters — the control scenario.",
            parameters=params,
            variation_type="baseline",
            tags=[strategy_type, "control"],
        ))

        # Generate variation pool
        variation_builders = [
            _aggressive_variation,
            _conservative_variation,
            _edge_case_variation,
            _alternative_variation,
            _budget_optimized_variation,
            _growth_focused_variation,
            _risk_averse_variation,
        ]

        slots = max(0, num_scenarios - 1)
        for i in range(slots):
            builder = variation_builders[i % len(variation_builders)]
            scenario = builder(params, cons, objectives, strategy_type)
            scenarios.append(scenario)

        return {
            "status": "success",
            "scenarios": scenarios,
            "count": len(scenarios),
            "model_note": "LLaMA would generate richer, context-aware scenario narratives",
        }
    except Exception as exc:
        return {
            "status": "error",
            "scenarios": [],
            "count": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Variation builders
# ---------------------------------------------------------------------------

def _build_scenario(
    label: str,
    description: str,
    parameters: dict[str, Any],
    variation_type: str,
    tags: list[str],
) -> dict[str, Any]:
    return {
        "scenario_id": uuid.uuid4().hex[:10],
        "label": label,
        "description": description,
        "parameters": copy.deepcopy(parameters),
        "variation_type": variation_type,
        "tags": tags,
    }


def _scale_numeric(value: Any, factor: float, floor: float | None = None) -> Any:
    """Multiply a numeric value by factor, respecting an optional floor."""
    if isinstance(value, (int, float)):
        result = value * factor
        if floor is not None:
            result = max(result, floor)
        return round(result, 4) if isinstance(value, float) else int(round(result))
    return value


def _adjust_params(
    params: dict[str, Any],
    factor: float,
    floor: float | None = 0.0,
) -> dict[str, Any]:
    """Scale all numeric values in params by factor."""
    adjusted = copy.deepcopy(params)
    for key, val in adjusted.items():
        adjusted[key] = _scale_numeric(val, factor, floor)
    return adjusted


def _clamp_to_constraints(
    params: dict[str, Any],
    constraints: dict[str, Any],
) -> dict[str, Any]:
    """Clamp parameter values to constraint bounds."""
    clamped = copy.deepcopy(params)
    min_vals = constraints.get("min", {})
    max_vals = constraints.get("max", {})
    for key in clamped:
        if not isinstance(clamped[key], (int, float)):
            continue
        if key in min_vals and isinstance(min_vals[key], (int, float)):
            clamped[key] = max(clamped[key], min_vals[key])
        if key in max_vals and isinstance(max_vals[key], (int, float)):
            clamped[key] = min(clamped[key], max_vals[key])
    return clamped


def _aggressive_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    adjusted = _clamp_to_constraints(
        _adjust_params(params, 1.30), constraints,
    )
    return _build_scenario(
        label="Aggressive",
        description="Parameters pushed 30% above baseline to test upside potential.",
        parameters=adjusted,
        variation_type="aggressive",
        tags=[strategy_type, "high-risk", "high-reward"],
    )


def _conservative_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    adjusted = _clamp_to_constraints(
        _adjust_params(params, 0.80), constraints,
    )
    return _build_scenario(
        label="Conservative",
        description="Parameters reduced 20% below baseline for risk-averse stance.",
        parameters=adjusted,
        variation_type="conservative",
        tags=[strategy_type, "low-risk", "stable"],
    )


def _edge_case_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    # Push to constraint boundaries
    edge = copy.deepcopy(params)
    max_vals = constraints.get("max", {})
    min_vals = constraints.get("min", {})
    for key in edge:
        if not isinstance(edge[key], (int, float)):
            continue
        # Alternate between min and max edges
        if key in max_vals and isinstance(max_vals[key], (int, float)):
            edge[key] = max_vals[key]
        elif key in min_vals and isinstance(min_vals[key], (int, float)):
            edge[key] = min_vals[key]
        else:
            edge[key] = _scale_numeric(edge[key], 1.50, 0.0)
    return _build_scenario(
        label="Edge Case",
        description="Parameters at constraint boundaries to test extremes.",
        parameters=edge,
        variation_type="edge_case",
        tags=[strategy_type, "boundary", "stress-test"],
    )


def _alternative_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    alt = copy.deepcopy(params)
    keys = [k for k, v in alt.items() if isinstance(v, (int, float))]
    # Invert the weighting: boost lower params, reduce higher ones
    if keys:
        values = [alt[k] for k in keys]
        median = sorted(values)[len(values) // 2] if values else 1
        for k in keys:
            if isinstance(alt[k], (int, float)) and median != 0:
                ratio = alt[k] / median if median else 1
                if ratio > 1:
                    alt[k] = _scale_numeric(alt[k], 0.85)
                else:
                    alt[k] = _scale_numeric(alt[k], 1.15)
    alt = _clamp_to_constraints(alt, constraints)
    return _build_scenario(
        label="Alternative Balance",
        description="Rebalanced parameters — boost underweighted, dampen overweighted.",
        parameters=alt,
        variation_type="alternative",
        tags=[strategy_type, "balanced", "creative"],
    )


def _budget_optimized_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    adjusted = _clamp_to_constraints(
        _adjust_params(params, 0.70), constraints,
    )
    return _build_scenario(
        label="Budget Optimized",
        description="Minimized cost parameters while maintaining key performance drivers.",
        parameters=adjusted,
        variation_type="conservative",
        tags=[strategy_type, "budget", "efficiency"],
    )


def _growth_focused_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    adjusted = _clamp_to_constraints(
        _adjust_params(params, 1.45), constraints,
    )
    return _build_scenario(
        label="Growth Focused",
        description="Maximum growth parameters — willing to sacrifice short-term margin.",
        parameters=adjusted,
        variation_type="aggressive",
        tags=[strategy_type, "growth", "scale"],
    )


def _risk_averse_variation(
    params: dict[str, Any],
    constraints: dict[str, Any],
    objectives: list[str],
    strategy_type: str,
) -> dict[str, Any]:
    adjusted = _clamp_to_constraints(
        _adjust_params(params, 0.65), constraints,
    )
    return _build_scenario(
        label="Risk Averse",
        description="Heavily conservative — prioritizes capital preservation.",
        parameters=adjusted,
        variation_type="conservative",
        tags=[strategy_type, "safe", "minimal-exposure"],
    )
