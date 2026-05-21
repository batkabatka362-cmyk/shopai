"""Persistent plan-invocation history for the substrate
learning loop.

``shopai plan <goal>`` produces a Plan. ``shopai plan
--execute`` runs the steps. ``shopai launch-audit`` reports
readiness. None of these alone record "the planner suggested
X, the operator ran it, did it actually work?". This module
is that recording layer.

Why this matters for the north-star bible
-----------------------------------------
The autonomous merchant vision needs the planner to LEARN
from outcomes. Today's deterministic planner picks seeds
from substring matching; tomorrow's LLM-driven planner picks
seeds from semantic retrieval. Either way, the FEEDBACK
LOOP -- "did the recommendation work?" -- is what lets the
system improve.

This module is the foundation for that loop. Subsequent
work (outcome correlation, planner self-improvement) reads
this history to score past suggestions.

Public surface
--------------
- ``PlanEvent`` -- one plan invocation (timestamp + goal +
  plan_dict + executed bool + outcome string)
- ``record_plan_invocation(goal, plan, store_id, executed,
  outcome=None)`` -- append an event; idempotent via
  generated event_id.
- ``record_outcome(event_id, outcome)`` -- update an
  existing event's outcome field. Used by post-execution
  correlation (e.g., when launch-audit confirms gaps
  closed).
- ``recent_history(since_seconds=86400*7)`` -- list recent
  events. Default 7-day window.
- ``clear()`` -- wipe the history (operator escape hatch).

The persistence pattern mirrors ``core.approval.alert_history``:
single JSON file at ``data/plan_history.json``, atomic write
via temp + rename, fail-open semantics (missing / corrupt
file -> empty history; the recorder is non-critical).

Test-environment guard
----------------------
Under pytest (``PYTEST_CURRENT_TEST`` env var set),
``record_plan_invocation`` and ``record_outcome``
short-circuit without writing -- prevents test fixtures from
polluting the production history. Mirrors the Pattern J
guards in ``engines._writeback_recorder`` and
``core.approval.alert_history``.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Persistence location. Operators can override via env if
# they want to test a separate history (e.g. for a staging
# clone of the autonomous controller).
_HISTORY_PATH = Path(
    os.environ.get(
        "SHOPAI_PLAN_HISTORY_PATH",
        "data/plan_history.json",
    )
)


@dataclass
class PlanEvent:
    """One plan invocation. Append-only -- the only update
    operation is ``record_outcome`` which sets the outcome
    field on an existing event."""

    event_id: str  # generated uuid4 prefix
    timestamp: float  # unix seconds
    goal: str
    store_id: str = ""
    # The full plan dict (Plan.to_dict()). Stored so future
    # analysis can reproduce / score / compare past plans.
    plan: dict[str, Any] = field(default_factory=dict)
    executed: bool = False
    # Outcome semantics:
    #   "" -- not yet evaluated
    #   "success" -- audit confirmed gaps closed / goal met
    #   "partial" -- some steps succeeded, gaps remain
    #   "fail" -- execution failed or audit got worse
    #   "skipped" -- dry-run only / operator never executed
    outcome: str = ""
    # Free-form notes (e.g. "audit completion_pct: 60 -> 100")
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Test-environment short-circuit. Set in pytest fixtures via
# PYTEST_CURRENT_TEST; the recorder no-ops to prevent
# production data pollution.
def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _load_history() -> list[dict[str, Any]]:
    """Fail-open read of the history file. Missing / corrupt
    -> empty list (recorder is non-critical)."""
    try:
        if not _HISTORY_PATH.exists():
            return []
        with _HISTORY_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict)]
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug(
            "plan_history: load failed (%s) -- returning "
            "empty", exc,
        )
        return []


def _atomic_write(events: list[dict[str, Any]]) -> None:
    """Write via temp file + rename. Either everyone sees
    the old file or everyone sees the new file -- no
    partial-write window."""
    try:
        _HISTORY_PATH.parent.mkdir(
            parents=True, exist_ok=True,
        )
    except OSError as exc:
        logger.debug(
            "plan_history: mkdir failed (%s)", exc,
        )
        return
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=".plan_history_",
            suffix=".json",
            dir=str(_HISTORY_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2, default=str)
            os.replace(temp_path_str, _HISTORY_PATH)
        except Exception:
            try:
                os.unlink(temp_path_str)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.debug(
            "plan_history: write failed (%s)", exc,
        )


def record_plan_invocation(
    *,
    goal: str,
    plan: dict[str, Any] | Any,
    store_id: str = "",
    executed: bool = False,
    outcome: str = "",
    notes: str = "",
) -> str:
    """Append a plan invocation to the history.

    Returns the generated ``event_id`` (caller can pass it
    later to ``record_outcome`` for post-execution
    correlation). Returns empty string in test environments
    or on any write failure.

    Accepts either a ``Plan`` instance or a pre-converted
    dict; calls ``.to_dict()`` if available.
    """
    if _is_test_environment():
        return ""

    plan_dict: dict[str, Any]
    if hasattr(plan, "to_dict"):
        try:
            plan_dict = plan.to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "plan_history: to_dict raised (%s)", exc,
            )
            plan_dict = {}
    elif isinstance(plan, dict):
        plan_dict = plan
    else:
        plan_dict = {}

    event_id = f"plan_{uuid.uuid4().hex[:12]}"
    event = PlanEvent(
        event_id=event_id,
        timestamp=time.time(),
        goal=(goal or "").strip(),
        store_id=str(store_id or ""),
        plan=plan_dict,
        executed=bool(executed),
        outcome=str(outcome or ""),
        notes=str(notes or ""),
    )

    events = _load_history()
    events.append(event.to_dict())
    # Keep history bounded -- last 1000 events. The learning
    # loop's window is days/weeks, not months/years, so
    # capping prevents the file growing unbounded.
    if len(events) > 1000:
        events = events[-1000:]
    _atomic_write(events)
    return event_id


def record_outcome(
    event_id: str,
    outcome: str,
    *,
    notes: str = "",
) -> bool:
    """Update an existing event's outcome field.

    Returns True on success, False when the event isn't
    found / file unreadable / test environment.

    Outcome strings: ``success`` | ``partial`` | ``fail`` |
    ``skipped`` (free-form is allowed; consumers should
    treat unknown values as "unknown").
    """
    if _is_test_environment() or not event_id:
        return False
    events = _load_history()
    found = False
    for e in events:
        if e.get("event_id") == event_id:
            e["outcome"] = str(outcome or "")
            if notes:
                e["notes"] = str(notes)
            found = True
            break
    if not found:
        return False
    _atomic_write(events)
    return True


def recent_history(
    since_seconds: int = 86400 * 7,
) -> list[dict[str, Any]]:
    """Return events from the last ``since_seconds`` window.

    Default 7-day window. Returns newest-first.
    """
    cutoff = time.time() - max(0, int(since_seconds))
    events = _load_history()
    recent = [
        e for e in events
        if float(e.get("timestamp", 0) or 0) >= cutoff
    ]
    recent.sort(
        key=lambda e: float(e.get("timestamp", 0) or 0),
        reverse=True,
    )
    return recent


def outcome_breakdown(
    *,
    since_seconds: int = 86400 * 7,
    goal: str | None = None,
    capability: str | None = None,
) -> dict[str, Any]:
    """Aggregate outcome counts over the history window.

    Filters:
      - ``goal`` -- exact goal phrase match (case-sensitive
        substring). None = no filter.
      - ``capability`` -- only events whose plan.steps
        include a step with this capability_name. None = no
        filter.

    Returns a dict with:
      - ``total`` -- number of matched events
      - ``executed_total`` -- subset with executed=True
      - ``by_outcome`` -- ``{outcome: count}``
      - ``success_rate`` -- success / executed_total (0.0
        when executed_total == 0)

    The learning loop's primary observability primitive: it
    tells the planner / operator "this goal succeeds N% of
    the time" or "capability X appears in plans that
    succeed M% of the time".
    """
    events = recent_history(since_seconds=since_seconds)
    if goal:
        goal_l = goal.lower()
        events = [
            e for e in events
            if goal_l in (e.get("goal", "") or "").lower()
        ]
    if capability:
        cap_name = capability
        filtered = []
        for e in events:
            plan = e.get("plan") or {}
            steps = plan.get("steps") or []
            for s in steps:
                if (
                    isinstance(s, dict)
                    and s.get("capability_name")
                    == cap_name
                ):
                    filtered.append(e)
                    break
        events = filtered

    by_outcome: dict[str, int] = {}
    executed_total = 0
    for e in events:
        out = (e.get("outcome") or "(none)").strip() or (
            "(none)"
        )
        by_outcome[out] = by_outcome.get(out, 0) + 1
        if e.get("executed"):
            executed_total += 1

    success_count = by_outcome.get("success", 0)
    success_rate = (
        success_count / executed_total
        if executed_total > 0 else 0.0
    )

    return {
        "total": len(events),
        "executed_total": executed_total,
        "by_outcome": dict(sorted(
            by_outcome.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )),
        "success_rate": round(success_rate, 3),
    }


def goal_breakdown(
    *,
    since_seconds: int = 86400 * 7,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Per-goal aggregate: which goals are most frequently
    planned, how often they succeed.

    Returns a list of ``{goal, count, success, success_rate}``
    dicts sorted by count desc. Top ``top_n`` returned.

    Useful for the operator dashboard: "which strategic
    goals am I planning most often + which actually work?"
    """
    events = recent_history(since_seconds=since_seconds)
    per_goal: dict[str, dict[str, int]] = {}
    for e in events:
        g = (e.get("goal") or "").strip()
        if not g:
            continue
        entry = per_goal.setdefault(g, {
            "count": 0, "success": 0, "executed": 0,
        })
        entry["count"] += 1
        if e.get("executed"):
            entry["executed"] += 1
        if e.get("outcome") == "success":
            entry["success"] += 1
    rows = []
    for g, stats in per_goal.items():
        executed = stats["executed"]
        rate = (
            stats["success"] / executed
            if executed > 0 else 0.0
        )
        rows.append({
            "goal": g,
            "count": stats["count"],
            "executed": executed,
            "success": stats["success"],
            "success_rate": round(rate, 3),
        })
    rows.sort(
        key=lambda r: (-r["count"], r["goal"]),
    )
    return rows[:max(1, int(top_n))]


def clear() -> None:
    """Wipe the history. Operator escape hatch / test
    cleanup."""
    if _is_test_environment():
        return
    if _HISTORY_PATH.exists():
        try:
            _HISTORY_PATH.unlink()
        except OSError as exc:
            logger.debug(
                "plan_history: unlink failed (%s)", exc,
            )


def _reset_for_tests(path: Path | None = None) -> None:
    """Test-only hook: override the history path so tests
    can write to a temp file without the test-env guard."""
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
