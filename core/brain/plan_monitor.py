"""Plan monitor — live watchdog during plan execution.

plan_verifier (v29-D4) pre-flights a plan before it runs. plan_monitor
is the *in-flight* companion: as each step completes, it checks:

  • expected vs observed progress (is the plan on track?)
  • invariants after each step (did we just break something?)
  • deadline consumption (are we burning the clock?)
  • unexpected state mutations (keys that shouldn't have changed)

Emits a ``StepVerdict`` per checked step (ok / warn / abort) so the
executor can decide whether to continue, pause, or trigger
plan_repair / recovery_planner.

Design choice: plan_monitor is stateful per ``plan_id`` because the
executor feeds it events; invariant_monitor is a stateless sweep.

Pure stdlib. Deterministic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.plan_monitor")


Status = Literal["ok", "warn", "abort"]


@dataclass
class ExpectedStep:
    name: str
    expected_duration_s: float = 0.0
    expected_state_after: dict[str, Any] = field(default_factory=dict)
    forbidden_state_changes: tuple[str, ...] = ()
    invariants: tuple[Callable[[dict[str, Any]], bool], ...] = ()
    invariant_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ExpectedStep.name required")
        if self.expected_duration_s < 0:
            raise ValueError("expected_duration_s must be ≥ 0")


@dataclass
class StepVerdict:
    step: str
    status: Status
    duration_s: float
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "duration_s": round(self.duration_s, 3),
            "violations": list(self.violations),
            "notes": list(self.notes),
        }


@dataclass
class MonitorSnapshot:
    plan_id: str
    expected_total_s: float
    elapsed_s: float
    started_ts: float
    verdicts: list[StepVerdict] = field(default_factory=list)
    status: Status = "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "expected_total_s": round(self.expected_total_s, 3),
            "elapsed_s": round(self.elapsed_s, 3),
            "started_ts": self.started_ts,
            "status": self.status,
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


@dataclass
class _PlanState:
    plan_id: str
    steps: dict[str, ExpectedStep]
    order: list[str]
    started_ts: float
    last_state: dict[str, Any]
    verdicts: list[StepVerdict] = field(default_factory=list)
    deadline_s: float | None = None
    status: Status = "ok"


def _worst(a: Status, b: Status) -> Status:
    rank = {"ok": 0, "warn": 1, "abort": 2}
    return a if rank[a] >= rank[b] else b


class PlanMonitor:
    def __init__(self) -> None:
        self._plans: dict[str, _PlanState] = {}

    # ── Lifecycle ────────────────────────────────────────

    def start(
        self,
        plan_id: str,
        steps: Iterable[ExpectedStep],
        *,
        initial_state: dict[str, Any] | None = None,
        deadline_s: float | None = None,
    ) -> None:
        if not plan_id:
            raise ValueError("plan_id required")
        step_list = list(steps)
        if not step_list:
            raise ValueError("at least one step required")
        if deadline_s is not None and deadline_s < 0:
            raise ValueError("deadline_s must be ≥ 0")
        if plan_id in self._plans:
            raise ValueError(f"plan {plan_id!r} already active")
        self._plans[plan_id] = _PlanState(
            plan_id=plan_id,
            steps={s.name: s for s in step_list},
            order=[s.name for s in step_list],
            started_ts=time.time(),
            last_state=dict(initial_state or {}),
            deadline_s=deadline_s,
        )

    def is_active(self, plan_id: str) -> bool:
        return plan_id in self._plans

    def finish(self, plan_id: str) -> MonitorSnapshot | None:
        if plan_id not in self._plans:
            return None
        snap = self.snapshot(plan_id)
        del self._plans[plan_id]
        return snap

    def cancel(self, plan_id: str) -> bool:
        return self._plans.pop(plan_id, None) is not None

    # ── Record step completion ───────────────────────────

    def record_step(
        self,
        plan_id: str,
        step: str,
        *,
        duration_s: float,
        state_after: dict[str, Any],
    ) -> StepVerdict:
        if plan_id not in self._plans:
            raise ValueError(f"unknown plan {plan_id!r}")
        if duration_s < 0:
            raise ValueError("duration_s must be ≥ 0")
        state = self._plans[plan_id]
        expected = state.steps.get(step)
        violations: list[str] = []
        notes: list[str] = []
        status: Status = "ok"

        if expected is None:
            notes.append("step not in plan schedule")
            status = "warn"
        else:
            # 1. Duration check — > 2× expected is warn, > 5× is abort.
            if expected.expected_duration_s > 0:
                ratio = duration_s / expected.expected_duration_s
                if ratio >= 5.0:
                    violations.append(
                        f"duration {duration_s:.2f}s > "
                        f"5× expected {expected.expected_duration_s:.2f}s"
                    )
                    status = _worst(status, "abort")
                elif ratio >= 2.0:
                    notes.append(
                        f"duration {duration_s:.2f}s > "
                        f"2× expected {expected.expected_duration_s:.2f}s"
                    )
                    status = _worst(status, "warn")

            # 2. Forbidden state changes
            for key in expected.forbidden_state_changes:
                if (
                    state.last_state.get(key)
                    != state_after.get(key)
                ):
                    violations.append(
                        f"forbidden mutation on {key!r}",
                    )
                    status = _worst(status, "abort")

            # 3. Expected state-after keys present + equal
            for key, want in expected.expected_state_after.items():
                got = state_after.get(key)
                if got != want:
                    violations.append(
                        f"state[{key}] expected={want!r} got={got!r}",
                    )
                    status = _worst(status, "warn")

            # 4. Run invariant predicates
            for idx, pred in enumerate(expected.invariants):
                try:
                    holds = bool(pred(state_after))
                except Exception as exc:
                    logger.debug(
                        "invariant %s/%d raised: %s",
                        step, idx, exc,
                    )
                    holds = False
                if not holds:
                    inv_name = (
                        expected.invariant_names[idx]
                        if idx < len(expected.invariant_names)
                        else f"inv_{idx}"
                    )
                    violations.append(f"invariant:{inv_name}")
                    status = _worst(status, "abort")

        # 5. Deadline check (global) — warn at 80 %, abort past deadline
        elapsed = time.time() - state.started_ts
        if state.deadline_s is not None:
            if elapsed >= state.deadline_s:
                violations.append(
                    f"deadline breached: {elapsed:.1f}s "
                    f"> {state.deadline_s:.1f}s"
                )
                status = _worst(status, "abort")
            elif elapsed >= 0.8 * state.deadline_s:
                notes.append(
                    f"deadline: {elapsed:.1f}s of "
                    f"{state.deadline_s:.1f}s consumed"
                )
                status = _worst(status, "warn")

        verdict = StepVerdict(
            step=step,
            status=status,
            duration_s=duration_s,
            violations=violations,
            notes=notes,
        )
        state.verdicts.append(verdict)
        state.status = _worst(state.status, status)
        # Don't re-advance state_after if aborting — caller may inspect
        # the mutation that caused the abort.
        state.last_state = dict(state_after)
        return verdict

    # ── Snapshot ────────────────────────────────────────

    def snapshot(self, plan_id: str) -> MonitorSnapshot | None:
        state = self._plans.get(plan_id)
        if state is None:
            return None
        expected_total = sum(
            s.expected_duration_s for s in state.steps.values()
        )
        return MonitorSnapshot(
            plan_id=state.plan_id,
            expected_total_s=expected_total,
            elapsed_s=time.time() - state.started_ts,
            started_ts=state.started_ts,
            verdicts=list(state.verdicts),
            status=state.status,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "active_plans": len(self._plans),
            "plans": sorted(self._plans.keys()),
        }
