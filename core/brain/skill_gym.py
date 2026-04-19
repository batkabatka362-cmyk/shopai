"""Skill gym — sandbox where new skills are practised before going live.

Freshly distilled skills (from ``skill_distiller``) have no live
usage history. Running them straight on production Shopify is risky.
skill_gym is the training arena:

  1. Drop in a candidate Skill + a list of ``GymScenario`` records
     (each carries a ``state``, an ``expected_change``, and a
     ``validate`` callable).
  2. The gym runs the skill against a ``WorldSimulator`` snapshot
     of each scenario's state, then checks the ``validate``
     predicate against the resulting state.
  3. Emits a ``GymReport`` with pass rate, per-scenario verdicts,
     and a recommended status: "ready" / "conditional" / "reject".

Ready = passed all scenarios (→ safe to mark the skill as live).
Conditional = passed the strict scenarios but failed edge cases
(→ keep gated behind a feature flag).
Reject = failed the strict scenarios (→ don't ship).

Pure stdlib. Deterministic given the scenarios + world state.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.skill_gym")


Recommendation = Literal["ready", "conditional", "reject"]


@dataclass
class GymScenario:
    name: str
    initial_state: dict[str, Any]
    actions: list[dict[str, Any]]
    validate: Callable[[dict[str, Any]], bool]
    strict: bool = True   # counted for "ready"; soft ones allow conditional
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("GymScenario.name required")


@dataclass
class ScenarioVerdict:
    name: str
    passed: bool
    strict: bool
    note: str = ""
    applied: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "strict": self.strict,
            "note": self.note,
            "applied": self.applied,
            "skipped": self.skipped,
        }


@dataclass
class GymReport:
    skill_name: str
    scenarios: list[ScenarioVerdict] = field(default_factory=list)
    recommendation: Recommendation = "reject"
    pass_rate: float = 0.0
    strict_pass_rate: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "recommendation": self.recommendation,
            "pass_rate": round(self.pass_rate, 4),
            "strict_pass_rate": round(self.strict_pass_rate, 4),
            "scenarios": [s.as_dict() for s in self.scenarios],
        }


# ── Engine ────────────────────────────────────────────────

class SkillGym:
    """Runs scenarios against a simulator; reports pass rate."""

    def __init__(
        self,
        *,
        simulator: Any = None,
    ) -> None:
        # simulator is injectable; if None, we lazily build a
        # WorldSimulator with default transitions.
        self._sim = simulator

    def _simulator(self):
        if self._sim is not None:
            return self._sim
        try:
            from core.brain.world_simulator import (
                WorldSimulator, default_transitions,
            )
            sim = WorldSimulator()
            for k, fn in default_transitions().items():
                sim.register(k, fn)
            self._sim = sim
        except Exception as exc:
            logger.debug("simulator lazy init failed: %s", exc)
            raise
        return self._sim

    # ── Run ──────────────────────────────────────────────

    def _run_scenario(
        self, scenario: GymScenario,
    ) -> ScenarioVerdict:
        sim = self._simulator()
        sim.seed(copy.deepcopy(scenario.initial_state))
        try:
            report = sim.apply(scenario.actions)
        except Exception as exc:
            logger.debug(
                "scenario %s apply raised: %s",
                scenario.name, exc,
            )
            return ScenarioVerdict(
                name=scenario.name,
                passed=False,
                strict=scenario.strict,
                note=f"apply_raised: {exc}",
            )
        applied = len(report.applied)
        skipped = len(report.skipped)
        try:
            passed = bool(scenario.validate(report.final_state))
        except Exception as exc:
            logger.debug(
                "scenario %s validate raised: %s",
                scenario.name, exc,
            )
            return ScenarioVerdict(
                name=scenario.name,
                passed=False,
                strict=scenario.strict,
                applied=applied,
                skipped=skipped,
                note=f"validate_raised: {exc}",
            )
        return ScenarioVerdict(
            name=scenario.name,
            passed=passed,
            strict=scenario.strict,
            applied=applied,
            skipped=skipped,
            note="" if passed else "validate returned False",
        )

    def evaluate(
        self,
        skill_name: str,
        scenarios: Iterable[GymScenario],
    ) -> GymReport:
        if not skill_name:
            raise ValueError("skill_name required")
        verdicts: list[ScenarioVerdict] = []
        for s in scenarios:
            verdicts.append(self._run_scenario(s))
        if not verdicts:
            return GymReport(
                skill_name=skill_name,
                scenarios=[],
                recommendation="reject",
                pass_rate=0.0,
                strict_pass_rate=0.0,
            )
        total_passed = sum(1 for v in verdicts if v.passed)
        strict_list = [v for v in verdicts if v.strict]
        strict_passed = sum(1 for v in strict_list if v.passed)
        pass_rate = total_passed / len(verdicts)
        strict_rate = (
            strict_passed / len(strict_list)
            if strict_list else 1.0
        )
        if strict_rate == 1.0 and pass_rate == 1.0:
            recommendation: Recommendation = "ready"
        elif strict_rate == 1.0:
            recommendation = "conditional"
        else:
            recommendation = "reject"
        return GymReport(
            skill_name=skill_name,
            scenarios=verdicts,
            recommendation=recommendation,
            pass_rate=pass_rate,
            strict_pass_rate=strict_rate,
        )

    def stats(self) -> dict[str, Any]:
        return {
            "simulator_ready": self._sim is not None,
        }
