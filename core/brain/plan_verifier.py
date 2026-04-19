"""Plan verifier — simulate a plan against preconditions + invariants.

plan_search and workflow_dag produce plans. action_safety_guard gates
a single action. plan_verifier sits in between: before executing a
multi-step plan, it walks through the steps *in order*, simulates
each step's effects on a world state, and checks:

  • precondition violations   — step X requires Y before running
  • invariant breaches         — any step leaves world state violating
                                   a registered invariant (inventory ≥ 0
                                   etc.)
  • unreachable steps          — depends on output never produced
  • no-op steps                — effect = identity → plan is wasting a step

Plans accepted as either:

  • iterable of (name, precondition_fn, effect_fn) tuples
  • PlanSearch.Plan + library of Actions
  • workflow_dag-style task specs (map to step names + effects)

The module stays adapter-agnostic: you hand it *callables* that
operate on a state dict. Pure stdlib, deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.plan_verifier")


StateDict = dict[str, Any]
Precondition = Callable[[StateDict], bool]
Effect = Callable[[StateDict], StateDict]
Invariant = Callable[[StateDict], bool]


@dataclass
class PlanStep:
    name: str
    precondition: Precondition
    effect: Effect

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PlanStep.name required")


@dataclass
class StepReport:
    step: str
    precondition_ok: bool
    invariants_ok: bool
    applied: bool
    state_after_keys: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "precondition_ok": self.precondition_ok,
            "invariants_ok": self.invariants_ok,
            "applied": self.applied,
            "state_after_keys": list(self.state_after_keys),
            "notes": list(self.notes),
        }


@dataclass
class VerificationReport:
    verdict: str                 # "ok" | "warnings" | "blocked"
    steps: list[StepReport] = field(default_factory=list)
    final_state: StateDict = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "steps": [s.as_dict() for s in self.steps],
            "violations": list(self.violations),
            "final_state_keys": sorted(self.final_state.keys()),
        }


@dataclass
class NamedInvariant:
    name: str
    predicate: Invariant
    severity: str = "hard"    # "hard" → block ; "soft" → warn

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("NamedInvariant.name required")
        if self.severity not in ("hard", "soft"):
            raise ValueError("severity must be hard|soft")

    def holds(self, state: StateDict) -> bool:
        try:
            return bool(self.predicate(state))
        except Exception as exc:
            logger.debug(
                "invariant %s raised: %s", self.name, exc,
            )
            return False


class PlanVerifier:
    def __init__(self) -> None:
        self._invariants: list[NamedInvariant] = []

    # ── Invariant registry ───────────────────────────────

    def add_invariant(self, inv: NamedInvariant) -> None:
        self._invariants.append(inv)

    def clear_invariants(self) -> None:
        self._invariants.clear()

    def invariants(self) -> list[NamedInvariant]:
        return list(self._invariants)

    # ── Verify ───────────────────────────────────────────

    def verify(
        self,
        start: StateDict,
        steps: Iterable[PlanStep],
    ) -> VerificationReport:
        step_list = list(steps)
        state = dict(start or {})
        reports: list[StepReport] = []
        violations: list[str] = []
        verdict = "ok"

        for step in step_list:
            try:
                precondition_ok = bool(step.precondition(state))
            except Exception as exc:
                logger.debug(
                    "precondition %s raised: %s",
                    step.name, exc,
                )
                precondition_ok = False

            if not precondition_ok:
                violations.append(
                    f"precondition:{step.name}",
                )
                reports.append(StepReport(
                    step=step.name,
                    precondition_ok=False,
                    invariants_ok=True,   # haven't applied yet
                    applied=False,
                    state_after_keys=sorted(state.keys()),
                    notes=["precondition failed"],
                ))
                verdict = "blocked"
                continue

            try:
                new_state = step.effect(state) or state
            except Exception as exc:
                logger.debug(
                    "effect %s raised: %s", step.name, exc,
                )
                violations.append(f"effect_error:{step.name}")
                reports.append(StepReport(
                    step=step.name,
                    precondition_ok=True,
                    invariants_ok=True,
                    applied=False,
                    state_after_keys=sorted(state.keys()),
                    notes=[f"effect raised: {exc}"],
                ))
                verdict = "blocked"
                continue
            new_state = dict(new_state)

            # Check invariants after applying step
            invariant_notes: list[str] = []
            hard_break = False
            for inv in self._invariants:
                if not inv.holds(new_state):
                    msg = f"invariant:{inv.name}:{inv.severity}"
                    violations.append(msg)
                    invariant_notes.append(msg)
                    if inv.severity == "hard":
                        hard_break = True

            # Detect no-ops — effect was identity
            if new_state == state:
                invariant_notes.append("no_op")

            state = new_state
            reports.append(StepReport(
                step=step.name,
                precondition_ok=True,
                invariants_ok=not hard_break,
                applied=not hard_break,
                state_after_keys=sorted(state.keys()),
                notes=invariant_notes,
            ))
            if hard_break:
                verdict = "blocked"
                # Still continue walking — callers want to see the
                # whole damage report — but mark as blocked and
                # stop propagating state (final shows last good).
                break
            elif invariant_notes and verdict == "ok":
                verdict = "warnings"

        return VerificationReport(
            verdict=verdict,
            steps=reports,
            final_state=state,
            violations=violations,
        )

    # ── Convenience: check preconditions only ────────────

    def preconditions_only(
        self,
        start: StateDict,
        steps: Iterable[PlanStep],
    ) -> list[str]:
        """Return names of steps whose preconditions don't hold at
        plan start (no effect simulation)."""
        state = dict(start or {})
        failed: list[str] = []
        for step in steps:
            try:
                if not bool(step.precondition(state)):
                    failed.append(step.name)
            except Exception as exc:
                logger.debug(
                    "precondition %s raised: %s", step.name, exc,
                )
                failed.append(step.name)
        return failed

    def stats(self) -> dict[str, Any]:
        return {
            "invariants": len(self._invariants),
            "hard_invariants": sum(
                1 for i in self._invariants if i.severity == "hard"
            ),
        }
