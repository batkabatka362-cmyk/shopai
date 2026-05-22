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
    """One plan invocation. Append-only except for the
    ``record_outcome`` update which sets the outcome /
    notes fields on an existing event."""

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
    #   "executed_ok" -- ran OK; outcome not yet verified
    #   "no_change" -- ran but no measurable change
    #   "revenue_up" / "revenue_flat" / "revenue_down" --
    #     set by ``shopai plan outcome`` after revenue
    #     correlation
    outcome: str = ""
    # Free-form notes (e.g. "audit completion_pct: 60 -> 100"
    # or "revenue: $1,234 -> $1,891 (+53.2%)")
    notes: str = ""
    # Pre-execution store stats snapshot (revenue / orders /
    # products / customers). Captured at execute time so
    # post-execution correlation can compute deltas without
    # external state. Empty when not captured (dry-run /
    # plan_history clients that don't supply it).
    pre_stats: dict[str, Any] = field(default_factory=dict)

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
    pre_stats: dict[str, Any] | None = None,
) -> str:
    """Append a plan invocation to the history.

    Returns the generated ``event_id`` (caller can pass it
    later to ``record_outcome`` for post-execution
    correlation). Returns empty string in test environments
    or on any write failure.

    Accepts either a ``Plan`` instance or a pre-converted
    dict; calls ``.to_dict()`` if available.

    ``pre_stats`` is a pre-execution snapshot of the
    store's headline metrics (revenue / orders / products /
    customers). Used by ``shopai plan outcome <event_id>``
    to compute revenue deltas without needing external
    state. Pass ``sm.get_stats(store_id)`` from the caller
    if available; defaults to empty dict.
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
        pre_stats=dict(pre_stats or {}),
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


def capability_degradations(
    *,
    recent_window_seconds: int = 86400 * 7,
    baseline_window_seconds: int = 86400 * 30,
    min_recent_sample: int = 2,
    min_baseline_sample: int = 5,
    drop_threshold: float = 0.2,
) -> list[dict[str, Any]]:
    """Detect capabilities whose RECENT reliability dropped
    versus the BASELINE window.

    For each capability that appears in both windows with
    enough samples:
      - baseline_rate -- success rate over baseline_window
      - recent_rate   -- success rate over recent_window
      - drop          -- baseline_rate - recent_rate

    Filters:
      - ``min_recent_sample`` -- skip caps with fewer than N
        recent executed plans (noise)
      - ``min_baseline_sample`` -- skip caps without
        established baseline
      - ``drop_threshold`` -- only return caps where drop
        exceeds this (default 0.2 = 20pp regression)

    Returns a list of ``{capability, baseline_rate,
    recent_rate, drop, recent_samples, baseline_samples}``
    sorted by drop desc (worst regression first).

    Operational signal: "this capability used to work; it
    isn't working anymore. Investigate."

    The recent window must be SHORTER than the baseline
    (the recent ratio is computed within the baseline as
    well, just over a tighter sub-window). Caller is
    responsible for sane window selection.
    """
    # Aggregate per-capability counts for both windows
    baseline_per_cap: dict[str, dict[str, int]] = (
        _aggregate_per_capability(baseline_window_seconds)
    )
    recent_per_cap: dict[str, dict[str, int]] = (
        _aggregate_per_capability(recent_window_seconds)
    )

    rows: list[dict[str, Any]] = []
    for cap_name, base_stats in baseline_per_cap.items():
        base_exec = base_stats["executed"]
        if base_exec < max(1, int(min_baseline_sample)):
            continue
        recent_stats = recent_per_cap.get(cap_name, {})
        recent_exec = recent_stats.get("executed", 0)
        if recent_exec < max(1, int(min_recent_sample)):
            continue
        base_rate = (
            base_stats["success"] / base_exec
            if base_exec > 0 else 0.0
        )
        recent_rate = (
            recent_stats.get("success", 0) / recent_exec
            if recent_exec > 0 else 0.0
        )
        drop = base_rate - recent_rate
        if drop < float(drop_threshold):
            continue
        rows.append({
            "capability": cap_name,
            "baseline_rate": round(base_rate, 3),
            "recent_rate": round(recent_rate, 3),
            "drop": round(drop, 3),
            "recent_samples": recent_exec,
            "baseline_samples": base_exec,
        })
    rows.sort(key=lambda r: -r["drop"])
    return rows


def _aggregate_per_capability(
    since_seconds: int,
) -> dict[str, dict[str, int]]:
    """Helper for capability degradation + leaderboard.
    Walks events in window, counts executed + success per
    capability with within-event dedup so a plan that
    mentions a cap twice still counts as 1 contribution.
    """
    events = recent_history(since_seconds=since_seconds)
    per_cap: dict[str, dict[str, int]] = {}
    for e in events:
        if not e.get("executed"):
            continue
        plan = e.get("plan") or {}
        steps = plan.get("steps") or []
        success = e.get("outcome") == "success"
        seen: set[str] = set()
        for s in steps:
            if not isinstance(s, dict):
                continue
            name = s.get("capability_name", "")
            if not name or name in seen:
                continue
            seen.add(name)
            entry = per_cap.setdefault(name, {
                "executed": 0, "success": 0,
            })
            entry["executed"] += 1
            if success:
                entry["success"] += 1
    return per_cap


def capability_leaderboard(
    *,
    since_seconds: int = 86400 * 30,
    min_sample_size: int = 2,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Per-capability reliability ranking from plan history.

    For each capability that appears in past plans, compute:
      - executed count (how many executed plans included it)
      - success count (how many of those resulted in
        ``outcome=success``)
      - success_rate = success / executed

    Filters:
      - ``min_sample_size`` -- skip capabilities below this
        executed-count threshold (small samples are noise).
        Default 2.

    Returns a list of ``{capability, executed_count,
    success_count, success_rate}`` sorted by success_rate
    desc, tie-broken by executed_count desc. Top ``top_n``
    returned.

    The operator-facing leaderboard primitive:
      ``shopai capabilities reliability`` -- "which
      capabilities have been most/least reliable across my
      fleet?"

    Future planner integration: when two candidates are
    tied at the same chain position, prefer the
    higher-reliability one.
    """
    per_cap = _aggregate_per_capability(since_seconds)

    rows: list[dict[str, Any]] = []
    for name, stats in per_cap.items():
        executed = stats["executed"]
        if executed < max(1, int(min_sample_size)):
            continue
        rate = (
            stats["success"] / executed
            if executed > 0 else 0.0
        )
        rows.append({
            "capability": name,
            "executed_count": executed,
            "success_count": stats["success"],
            "success_rate": round(rate, 3),
        })
    rows.sort(
        key=lambda r: (
            -r["success_rate"],
            -r["executed_count"],
            r["capability"],
        ),
    )
    return rows[:max(1, int(top_n))]


def successful_plans(
    *,
    since_seconds: int = 86400 * 30,
    exclude_store_id: str = "",
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Return successful past plans ranked by recency +
    frequency. The recommendation primitive for cross-store
    learning.

    Filters:
      - ``since_seconds`` -- look-back window (default 30
        days)
      - ``exclude_store_id`` -- skip plans from this store
        (when recommending for store X, don't surface X's
        own past plans -- transfer is the point)

    Each returned row:

        {
          "goal":          str (original goal phrase),
          "capabilities":  list[str] (capability_names from
                           plan.steps),
          "cli_sequence":  list[str] (from the plan dict),
          "success_count": int (how many times this exact
                           goal + capability combo succeeded),
          "last_success":  float (latest success timestamp),
          "stores":        list[str] (store_ids where it
                           succeeded).
        }

    Ranked by ``success_count`` desc, tie-broken by
    ``last_success`` desc. Top ``top_n`` returned.
    """
    events = recent_history(since_seconds=since_seconds)
    # Filter: successful + not excluded store
    candidates = [
        e for e in events
        if e.get("outcome") == "success"
        and (
            not exclude_store_id
            or e.get("store_id", "") != exclude_store_id
        )
    ]
    if not candidates:
        return []

    # Group by (goal, capability tuple)
    grouped: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for e in candidates:
        goal = (e.get("goal") or "").strip()
        plan = e.get("plan") or {}
        steps = plan.get("steps") or []
        caps = tuple(
            s.get("capability_name", "")
            for s in steps
            if isinstance(s, dict)
            and s.get("capability_name")
        )
        if not goal or not caps:
            continue
        key = (goal, caps)
        if key not in grouped:
            grouped[key] = {
                "goal": goal,
                "capabilities": list(caps),
                "cli_sequence": list(
                    plan.get("cli_sequence") or []
                ),
                "success_count": 0,
                "last_success": 0.0,
                "stores": set(),
            }
        entry = grouped[key]
        entry["success_count"] += 1
        ts = float(e.get("timestamp", 0) or 0)
        if ts > entry["last_success"]:
            entry["last_success"] = ts
        sid = e.get("store_id", "")
        if sid:
            entry["stores"].add(sid)

    rows = []
    for entry in grouped.values():
        rows.append({
            "goal": entry["goal"],
            "capabilities": entry["capabilities"],
            "cli_sequence": entry["cli_sequence"],
            "success_count": entry["success_count"],
            "last_success": entry["last_success"],
            "stores": sorted(entry["stores"]),
        })
    rows.sort(
        key=lambda r: (
            -r["success_count"],
            -r["last_success"],
        ),
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


def correlate_outcome_by_stats(
    event_id: str,
    current_stats: dict[str, Any],
) -> dict[str, Any]:
    """Compute a revenue / order / product delta for a
    past plan invocation by comparing the supplied
    ``current_stats`` against the event's pre_stats
    snapshot. Updates the event's outcome + notes.

    Outcome strings set:
      - ``revenue_up``   -- revenue grew vs pre_stats
      - ``revenue_flat`` -- within +/- 1% of pre_stats
      - ``revenue_down`` -- revenue dropped vs pre_stats

    When the event's pre_stats is empty (not captured at
    execute time) -- returns
    ``{"error": "no_pre_stats_baseline"}`` without updating.

    Returns a dict with the delta + outcome string, or
    error key.

    Pattern J test guard short-circuits writes; reads still
    work so tests can call this to verify the computation
    logic without polluting production history.
    """
    if not event_id:
        return {"error": "missing_event_id"}

    events = _load_history()
    target = None
    for e in events:
        if e.get("event_id") == event_id:
            target = e
            break
    if target is None:
        return {"error": "event_not_found"}

    pre = target.get("pre_stats") or {}
    if not pre:
        return {"error": "no_pre_stats_baseline"}

    def _f(d: dict[str, Any], k: str) -> float:
        try:
            return float(d.get(k, 0) or 0)
        except (ValueError, TypeError):
            return 0.0

    pre_rev = _f(pre, "total_revenue") or _f(pre, "revenue")
    cur_rev = (
        _f(current_stats, "total_revenue")
        or _f(current_stats, "revenue")
    )
    pre_orders = _f(pre, "orders")
    cur_orders = _f(current_stats, "orders")
    pre_products = _f(pre, "products")
    cur_products = _f(current_stats, "products")

    rev_delta = cur_rev - pre_rev
    if pre_rev > 0:
        rev_delta_pct = (rev_delta / pre_rev) * 100
    elif cur_rev > 0:
        rev_delta_pct = 100.0  # 0 -> N is +100%
    else:
        rev_delta_pct = 0.0

    # Bucket the outcome by revenue trajectory. 1%
    # threshold separates "real movement" from noise.
    if rev_delta_pct >= 1.0:
        outcome = "revenue_up"
    elif rev_delta_pct <= -1.0:
        outcome = "revenue_down"
    else:
        outcome = "revenue_flat"

    notes = (
        f"revenue: ${pre_rev:,.2f} -> ${cur_rev:,.2f} "
        f"({rev_delta_pct:+.1f}%); "
        f"orders: {pre_orders:.0f} -> {cur_orders:.0f}; "
        f"products: {pre_products:.0f} -> "
        f"{cur_products:.0f}"
    )

    # Persist the new outcome + notes. Idempotent overwrite.
    target["outcome"] = outcome
    target["notes"] = notes
    if not _is_test_environment():
        _atomic_write(events)

    return {
        "ok": True,
        "outcome": outcome,
        "revenue_delta": rev_delta,
        "revenue_delta_pct": round(rev_delta_pct, 2),
        "orders_delta": cur_orders - pre_orders,
        "products_delta": cur_products - pre_products,
        "notes": notes,
    }


def _reset_for_tests(path: Path | None = None) -> None:
    """Test-only hook: override the history path so tests
    can write to a temp file without the test-env guard."""
    global _HISTORY_PATH
    if path is not None:
        _HISTORY_PATH = path
