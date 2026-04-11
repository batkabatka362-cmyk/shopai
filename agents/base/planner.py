"""Shared planner primitives for domain agents.

Audit pass 37 — extracted from the 7 near-identical
``create_plan`` bodies that existed in
``agents/{product,marketing,content,finance,operations,
customer,research}/planner.py``.

Each domain planner had the same five-step shape:

  1. Defensive coercion of ``goal`` / ``context`` / ``constraints``
     (added in pass 35).
  2. Call ``_select_engines(goal, context)`` to pick engines.
  3. Build an ordered list of step dicts with a per-engine
     ``input`` payload plus a ``depends_on`` list.
  4. Call ``_determine_strategy(goal, context)`` to label the
     plan.
  5. Return a ``{"engines": [...], "strategy": ..., ...}`` dict.

Only the **domain knowledge** (what engines each agent owns,
what payload each engine wants, which steps depend on which)
was actually agent-specific. Everything else was duplicated 7
times which made every defensive bug fix in passes 30-35 a
7-file copy/paste exercise.

This module gives the agents two entry points:

  * ``create_plan_base(goal, context, constraints, *,
    engine_capabilities, goal_engine_map, default_engines,
    build_engine_input, get_dependencies, determine_strategy)``
    — the full planner contract. Each domain planner passes
    its own ``engine_capabilities`` dict + helper functions,
    and the base handles argument coercion, iteration, step
    wrapping, and the return shape.

  * ``engine_purpose(capabilities, engine_name)`` — the safe
    ``provides[0]`` lookup added in pass 35, shared across all
    planners so they can't drift apart on this defensive
    detail.

  * ``wrap_engine_input(data)`` — wraps a raw data dict in the
    standard ``{"status": "success", "data": ..., "meta": {},
    "error": None}`` envelope every domain planner used.
"""
from __future__ import annotations

from typing import Any, Callable


# Type aliases for the domain-supplied helper functions. Kept
# as ``Callable[..., Any]`` rather than Protocols so the
# existing module-level functions in each domain planner can
# be passed in without any annotation changes.
BuildInputFn = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
GetDepsFn = Callable[[str, list[dict]], list[str]]
DetermineStrategyFn = Callable[[str, dict[str, Any]], str]


def engine_purpose(
    capabilities: dict[str, Any],
    engine_name: str,
) -> str:
    """Safe lookup for an engine's primary purpose string.

    Returns ``"unknown"`` when the engine is missing from
    ``capabilities`` or its ``provides`` list is empty.
    Audit pass 35 added this defensive pattern to each of the
    7 domain planners; pass 37 hoists it here so they can't
    drift.
    """
    cap = capabilities.get(engine_name) if isinstance(capabilities, dict) else None
    if not isinstance(cap, dict):
        return "unknown"
    provides = cap.get("provides") or []
    if not isinstance(provides, list) or not provides:
        return "unknown"
    first = provides[0]
    return first if isinstance(first, str) else "unknown"


def wrap_engine_input(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap a raw data dict in the standard engine-input envelope.

    Every domain planner's ``_build_engine_input`` returned the
    same ``{"status": "success", "data": ..., "meta": {},
    "error": None}`` shape. Centralising it here means a
    future change to the envelope (e.g. adding a trace id) is
    a one-file change.
    """
    return {
        "status": "success",
        "data": data if isinstance(data, dict) else {},
        "meta": {},
        "error": None,
    }


def _select_engines(
    goal_lower: str,
    goal_engine_map: dict[str, list[str]],
    default_engines: list[str],
) -> list[str]:
    """Select engines based on a substring match against the goal.

    Mirrors the original per-planner logic: iterate
    ``goal_engine_map`` in dict order, return the first value
    whose key appears as a substring of the lowered goal.
    Falls back to ``default_engines`` on no match.
    """
    if not isinstance(goal_engine_map, dict):
        return list(default_engines) if isinstance(default_engines, list) else []
    for key, engines in goal_engine_map.items():
        if not isinstance(key, str) or not isinstance(engines, list):
            continue
        if key in goal_lower:
            return engines
    return list(default_engines) if isinstance(default_engines, list) else []


def create_plan_base(
    goal: str,
    context: dict[str, Any],
    constraints: dict[str, Any],
    *,
    engine_capabilities: dict[str, Any],
    goal_engine_map: dict[str, list[str]],
    default_engines: list[str],
    build_engine_input: BuildInputFn,
    get_dependencies: GetDepsFn,
    determine_strategy: DetermineStrategyFn,
) -> dict[str, Any]:
    """Run the full planner contract, delegating domain decisions.

    Args:
        goal: free-text goal string (``""`` after coercion if
            the caller passed None / non-string).
        context: agent context bag. Coerced to ``{}`` on
            non-dict.
        constraints: caller-side constraints (budget, time,
            etc.). Coerced to ``{}`` on non-dict.
        engine_capabilities: agent-specific
            ``{engine_name: {"provides": [...], "requires":
            [...], "optional": [...]}}`` dict. Used only for
            the ``purpose`` field lookup.
        goal_engine_map: agent-specific substring → engine
            list mapping. First substring match wins.
        default_engines: fallback engine list when no
            ``goal_engine_map`` key matches.
        build_engine_input: agent-specific
            ``(engine_name, context, constraints) -> dict``
            callback that returns the envelope dict for one
            step.
        get_dependencies: agent-specific
            ``(engine_name, existing_steps) -> list[str]``
            callback that returns the names of previous steps
            this step depends on.
        determine_strategy: agent-specific
            ``(goal_lower, context) -> str`` callback.

    Returns:
        The standard plan envelope::

            {
                "engines": [
                    {"name": str, "purpose": str, "input": {...},
                     "depends_on": [...]},
                    ...
                ],
                "strategy": str,
                "estimated_steps": int,
                "goal": str,   # the original (pre-coercion) goal
            }
    """
    # Defensive: never assume caller args match the declared
    # types. Mirrors the pass-35 coercion that previously
    # lived in every domain planner.
    goal = goal if isinstance(goal, str) else ""
    context = context if isinstance(context, dict) else {}
    constraints = constraints if isinstance(constraints, dict) else {}

    goal_lower = goal.lower().replace(" ", "_")
    engines_needed = _select_engines(goal_lower, goal_engine_map, default_engines)

    steps: list[dict[str, Any]] = []
    for engine_name in engines_needed:
        if not isinstance(engine_name, str) or not engine_name:
            continue
        try:
            engine_input = build_engine_input(engine_name, context, constraints)
        except Exception:  # noqa: BLE001
            # A buggy build_engine_input must not crash the
            # entire plan — mark the step with an empty
            # payload and let the executor surface the engine
            # failure naturally.
            engine_input = wrap_engine_input({})
        if not isinstance(engine_input, dict):
            engine_input = wrap_engine_input({})

        try:
            depends_on = get_dependencies(engine_name, steps)
        except Exception:  # noqa: BLE001
            depends_on = []
        if not isinstance(depends_on, list):
            depends_on = []

        steps.append({
            "name": engine_name,
            "purpose": engine_purpose(engine_capabilities, engine_name),
            "input": engine_input,
            "depends_on": depends_on,
        })

    try:
        strategy = determine_strategy(goal_lower, context)
    except Exception:  # noqa: BLE001
        strategy = "balanced"
    if not isinstance(strategy, str):
        strategy = "balanced"

    return {
        "engines": steps,
        "strategy": strategy,
        "estimated_steps": len(steps),
        "goal": goal,
    }
