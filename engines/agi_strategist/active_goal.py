"""Active goal persistence for the autonomous controller.

The strategist's plan needs to outlive a single cycle: an
operator sets a goal once, and the autonomous loop should
keep biasing its engine selection toward that goal's
substrategies for the remainder of the horizon.

This module is the tiny persistence layer between
:mod:`engines.agi_strategist.decomposer` (which generates
the plan) and ``core.autonomous.controller`` (which consumes
the recommended engines per cycle).

Storage: ``data/.active_goal.json`` (gitignored via ``/data/``
in ``.gitignore``; same hygiene as the Shopify token cache).
Pattern J: under pytest the file path is redirected to a
temp location so tests don't pollute the operator's real
active goal.

Public API
----------

  * :func:`set_active_goal` -- run the strategist and persist
    the resulting plan.
  * :func:`get_active_goal` -- read the persisted record;
    returns None if no goal is set.
  * :func:`clear_active_goal` -- remove the file. Returns
    True if a goal was cleared, False if none existed.
  * :func:`recommended_engines_for_active_plan` -- flat
    deduplicated engine list across the plan's substrategies,
    in priority order. This is the controller's main hook.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from .flow import AGIStrategistEngine

logger = get_logger("engines.agi_strategist.active_goal")


def _goal_file() -> Path:
    """Resolve the goal-file path.

    Under pytest, redirect to a temp-dir file so tests don't
    pollute the operator's real active goal. The env var
    ``SHOPAI_ACTIVE_GOAL_PATH`` overrides everything for
    callers that want to run a custom path.
    """
    override = os.environ.get("SHOPAI_ACTIVE_GOAL_PATH")
    if override:
        return Path(override)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        import tempfile
        return Path(tempfile.gettempdir()) / "shopai_test_active_goal.json"
    return Path(__file__).resolve().parents[2] / "data" / ".active_goal.json"


def set_active_goal(
    *,
    goal: str,
    horizon_days: int = 90,
    current_state: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Run the strategist and persist the active goal + plan.

    Args:
        goal: Operator goal text.
        horizon_days: Strategy horizon. Default 90 (one quarter).
        current_state: Optional metrics snapshot.
        constraints: Optional list of constraints.

    Returns:
        Dict with the persisted record:
        ``{goal, set_at, horizon_days, plan, status, error}``.
        On strategist failure, ``status="error"`` and the file
        is NOT written (so an old plan stays active rather than
        being clobbered with garbage).
    """
    engine = AGIStrategistEngine()
    envelope = engine.run({
        "goal": goal,
        "horizon_days": horizon_days,
        "current_state": current_state or {},
        "constraints": constraints or [],
    })
    if envelope.get("status") != "success":
        return {
            "goal": goal,
            "set_at": time.time(),
            "horizon_days": horizon_days,
            "plan": {},
            "status": envelope.get("status", "error"),
            "error": envelope.get("error", "strategist_failed"),
        }

    record: dict[str, Any] = {
        "goal": goal,
        "set_at": time.time(),
        "horizon_days": int(horizon_days),
        "plan": envelope.get("data", {}),
        "status": "success",
        "error": None,
    }

    path = _goal_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2))
    except OSError as exc:
        logger.warning(
            "active_goal: failed to persist to %s: %s", path, exc,
        )
        record["status"] = "error"
        record["error"] = f"persist_failed: {exc}"
    return record


def get_active_goal() -> dict[str, Any] | None:
    """Read the persisted active-goal record. None if none set.

    Failures (file missing / corrupt JSON / permission error)
    all return None silently -- the controller treats "no
    active goal" as a normal state.
    """
    path = _goal_file()
    if not path.exists():
        return None
    try:
        raw = path.read_text()
    except OSError as exc:
        logger.debug("active_goal: read failed: %s", exc)
        return None
    try:
        record = json.loads(raw)
        return record if isinstance(record, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("active_goal: JSON parse failed: %s", exc)
        return None


def clear_active_goal() -> bool:
    """Remove the active-goal file.

    Returns True if a file existed and was removed; False if
    none existed. Filesystem errors are logged but the
    function returns False rather than raising (the caller's
    flow doesn't depend on the exact removal result).
    """
    path = _goal_file()
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.debug("active_goal: unlink failed: %s", exc)
        return False


def recommended_engines_for_active_plan() -> list[str]:
    """Return the deduplicated engine list from the active
    plan's substrategies, in priority order.

    Priority is taken from each substrategy's ``priority``
    field (1 = highest). Within a priority bucket, the order
    is preserved from the plan. Returns ``[]`` when no plan
    is active or the plan has no recommended engines.
    """
    record = get_active_goal()
    if not record:
        return []
    plan = record.get("plan") or {}
    substrategies = plan.get("substrategies") or []
    if not isinstance(substrategies, list):
        return []

    # Sort substrategies by priority (1 highest); stable so
    # equal priorities retain the LLM/template ordering.
    indexed = []
    for idx, s in enumerate(substrategies):
        if not isinstance(s, dict):
            continue
        try:
            prio = int(s.get("priority", 3))
        except (TypeError, ValueError):
            prio = 3
        indexed.append((prio, idx, s))
    indexed.sort(key=lambda t: (t[0], t[1]))

    engines: list[str] = []
    seen: set[str] = set()
    for _, _, s in indexed:
        engines_raw = s.get("recommended_engines") or []
        if not isinstance(engines_raw, list):
            continue
        for e in engines_raw:
            name = str(e or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            engines.append(name)
    return engines
