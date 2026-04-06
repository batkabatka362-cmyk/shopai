"""Mind — the unified cognitive loop.

Mind is the conductor that ties all 9 cognitive modules together
into one coherent cycle. Each cycle the AI:

    1. PERCEIVE       Pull recent data into a CycleContext
    2. REFLECT        Run Reflection over recent episodes
    3. SET_GOALS      Generate goals from SelfModel + Curiosity
    4. PLAN           Decompose top goal via Planner
    5. IMAGINE        Score the plan via Imagination
    6. PREDICT        Ask TheoryOfMind how external agents will react
    7. ACT            Pick + invoke a Skill, or surface a recommendation
    8. LEARN          Record outcomes back into SelfModel + memory
    9. CONSOLIDATE    Periodically run Consolidation (every Nth cycle)

Mind is a thin orchestrator. All real intelligence lives in the
specialized modules; Mind just sequences them, threads context
between them, and produces a CycleReport summarizing what
happened in the cycle.

This module is intentionally framework-light. It doesn't need
the autonomous controller, doesn't need real Shopify, doesn't
need an LLM. Anything missing degrades gracefully (e.g. no
LLM → planner falls back to heuristics; no SkillRegistry → act
phase emits a recommendation instead of invoking).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

from core.cognitive.consolidation import Consolidation
from core.cognitive.curiosity import Curiosity, CuriosityRecommendation
from core.cognitive.goals import GoalManager
from core.cognitive.imagination import Imagination, ImaginedPlan
from core.cognitive.planner import Plan, Planner
from core.cognitive.reflection import Reflection, ReflectionReport
from core.cognitive.self_model import SelfModel
from core.cognitive.skill_registry import (
    SkillNotFound,
    SkillNotInvocable,
    SkillRegistry,
)
from core.cognitive.theory_of_mind import Prediction, TheoryOfMind

logger = get_logger("cognitive.mind")


@dataclass
class CycleReport:
    """Summary of one Mind cycle."""
    cycle_number: int
    started_at: float
    finished_at: float = 0.0

    perceived_inputs: int = 0
    reflection: Optional[ReflectionReport] = None
    goals_proposed: list[str] = field(default_factory=list)
    selected_goal_id: Optional[str] = None
    plan: Optional[Plan] = None
    imagined_plan: Optional[ImaginedPlan] = None
    curiosity: Optional[CuriosityRecommendation] = None
    predictions: list[Prediction] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    learning_updates: int = 0
    consolidation_ran: bool = False

    notes: list[str] = field(default_factory=list)
    error: str = ""

    def duration_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "duration_s": round(self.duration_s(), 3),
            "perceived_inputs": self.perceived_inputs,
            "reflection": self.reflection.to_dict() if self.reflection else None,
            "goals_proposed": list(self.goals_proposed),
            "selected_goal_id": self.selected_goal_id,
            "plan_step_count": self.plan.step_count() if self.plan else 0,
            "imagined_score": (
                self.imagined_plan.expected_score
                if self.imagined_plan else None
            ),
            "curiosity": self.curiosity.to_dict() if self.curiosity else None,
            "predictions": [p.to_dict() for p in self.predictions],
            "actions_taken": list(self.actions_taken),
            "learning_updates": self.learning_updates,
            "consolidation_ran": self.consolidation_ran,
            "notes": list(self.notes),
            "error": self.error,
        }

    def headline(self) -> str:
        """One-line human-readable summary."""
        parts = [f"cycle {self.cycle_number}"]
        if self.selected_goal_id:
            parts.append(f"goal={self.selected_goal_id[:14]}")
        if self.plan:
            parts.append(f"steps={self.plan.step_count()}")
        if self.actions_taken:
            parts.append(f"acts={len(self.actions_taken)}")
        if self.error:
            parts.append(f"ERR={self.error[:40]}")
        parts.append(f"{self.duration_s():.2f}s")
        return " ".join(parts)


@dataclass
class CycleContext:
    """Mutable context threaded through one cycle's phases."""
    cycle_number: int
    started_at: float
    inputs: dict[str, Any] = field(default_factory=dict)
    perception: dict[str, Any] = field(default_factory=dict)


class Mind:
    """The unified cognitive loop.

    Wires up all 9 cognitive modules. Any module can be replaced
    via constructor injection for tests; missing modules are
    detected and the cycle gracefully skips dependent phases.
    """

    def __init__(
        self,
        *,
        self_model: Optional[SelfModel] = None,
        goal_manager: Optional[GoalManager] = None,
        reflection: Optional[Reflection] = None,
        planner: Optional[Planner] = None,
        imagination: Optional[Imagination] = None,
        curiosity: Optional[Curiosity] = None,
        consolidation: Optional[Consolidation] = None,
        skill_registry: Optional[SkillRegistry] = None,
        theory_of_mind: Optional[TheoryOfMind] = None,
        memory: Any = None,
        consolidate_every_n: int = 10,
    ) -> None:
        self.self_model = self_model
        self.goal_manager = goal_manager
        self.reflection = reflection
        self.planner = planner
        self.imagination = imagination
        self.curiosity = curiosity
        self.consolidation = consolidation
        self.skill_registry = skill_registry
        self.theory_of_mind = theory_of_mind
        self.memory = memory

        self._cycle_count = 0
        self._consolidate_every_n = max(1, int(consolidate_every_n))

    # ── Public API ─────────────────────────────────────────────

    def run_cycle(
        self,
        inputs: Optional[dict[str, Any]] = None,
    ) -> CycleReport:
        """Run one full cognitive cycle.

        Inputs are an opaque dict the perceive phase can use. The
        default phases don't need any specific shape — they pull
        from the injected memory + self-model.
        """
        self._cycle_count += 1
        ctx = CycleContext(
            cycle_number=self._cycle_count,
            started_at=time.time(),
            inputs=dict(inputs or {}),
        )
        report = CycleReport(
            cycle_number=ctx.cycle_number,
            started_at=ctx.started_at,
        )

        try:
            self._phase_perceive(ctx, report)
            self._phase_reflect(ctx, report)
            self._phase_set_goals(ctx, report)
            self._phase_plan(ctx, report)
            self._phase_imagine(ctx, report)
            self._phase_predict(ctx, report)
            self._phase_act(ctx, report)
            self._phase_learn(ctx, report)
            self._phase_consolidate(ctx, report)
        except Exception as exc:  # noqa: BLE001
            report.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Mind cycle %d failed", ctx.cycle_number)

        report.finished_at = time.time()
        logger.info("Mind cycle %d: %s", ctx.cycle_number, report.headline())
        return report

    def cycle_count(self) -> int:
        return self._cycle_count

    # ── Phase 1: PERCEIVE ─────────────────────────────────────

    def _phase_perceive(self, ctx: CycleContext, report: CycleReport) -> None:
        """Gather recent data into ctx.perception.

        Default implementation just notes how many inputs were
        passed in and asks the SelfModel for current strengths/
        weaknesses. Real callers can subclass Mind to fold in
        Shopify data, daemon timestamps, etc.
        """
        ctx.perception["inputs"] = ctx.inputs
        report.perceived_inputs = len(ctx.inputs)

        if self.self_model is not None:
            try:
                ctx.perception["strengths"] = self.self_model.strengths(top_n=3)
                ctx.perception["weaknesses"] = self.self_model.weaknesses(top_n=3)
                ctx.perception["gaps"] = self.self_model.knowledge_gaps(top_n=3)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"perceive: self_model failed: {exc}")

    # ── Phase 2: REFLECT ──────────────────────────────────────

    def _phase_reflect(self, ctx: CycleContext, report: CycleReport) -> None:
        """Run Reflection over recent memory episodes."""
        if self.reflection is None:
            return
        try:
            report.reflection = self.reflection.reflect(apply=True)
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"reflect: {exc}")

    # ── Phase 3: SET_GOALS ────────────────────────────────────

    def _phase_set_goals(self, ctx: CycleContext, report: CycleReport) -> None:
        """Generate goals from SelfModel weaknesses + Curiosity."""
        if self.goal_manager is None:
            return

        # From SelfModel
        if self.self_model is not None:
            try:
                ids = self.goal_manager.propose_from_self_model(self.self_model)
                report.goals_proposed.extend(ids)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"set_goals (self_model): {exc}")

        # From Curiosity
        if self.curiosity is not None:
            try:
                gid = self.curiosity.propose_exploration_goal()
                if gid:
                    report.goals_proposed.append(gid)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"set_goals (curiosity): {exc}")

        # Pick the next goal to work on
        try:
            picked = self.goal_manager.pick_next()
            if picked:
                report.selected_goal_id = picked["id"]
                ctx.perception["goal"] = picked
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"set_goals (pick_next): {exc}")

    # ── Phase 4: PLAN ─────────────────────────────────────────

    def _phase_plan(self, ctx: CycleContext, report: CycleReport) -> None:
        """Decompose the selected goal."""
        if self.planner is None:
            return
        goal = ctx.perception.get("goal")
        if not goal:
            return
        try:
            report.plan = self.planner.plan(goal, context=ctx.perception)
            ctx.perception["plan"] = report.plan
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"plan: {exc}")

    # ── Phase 5: IMAGINE ──────────────────────────────────────

    def _phase_imagine(self, ctx: CycleContext, report: CycleReport) -> None:
        """Score the plan via Imagination."""
        if self.imagination is None:
            return
        plan = ctx.perception.get("plan")
        if not plan:
            return
        try:
            report.imagined_plan = self.imagination.imagine_plan(plan)
            ctx.perception["imagined"] = report.imagined_plan
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"imagine: {exc}")

    # ── Phase 6: PREDICT (TheoryOfMind) ───────────────────────

    def _phase_predict(self, ctx: CycleContext, report: CycleReport) -> None:
        """Ask TheoryOfMind how each known agent might react.

        For each plan step, run predict_response across every known
        agent and collect non-None predictions. The result is a flat
        list — the action phase / human reviewer can drill in.
        """
        if self.theory_of_mind is None:
            return
        plan = ctx.perception.get("plan")
        if not plan or not getattr(plan, "steps", None):
            return
        try:
            agents = self.theory_of_mind.list_agents()
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"predict (list_agents): {exc}")
            return
        if not agents:
            return

        for step in plan.steps[:3]:  # cap at 3 to keep output short
            description = getattr(step, "description", str(step))
            for agent in agents:
                try:
                    pred = self.theory_of_mind.predict_response(
                        agent.id, description,
                    )
                except Exception:  # noqa: BLE001
                    continue
                if pred is not None:
                    report.predictions.append(pred)

    # ── Phase 7: ACT ──────────────────────────────────────────

    def _phase_act(self, ctx: CycleContext, report: CycleReport) -> None:
        """Either invoke a matching Skill or record a recommendation.

        We look for a validated skill whose name matches the goal's
        first plan step. If found, invoke it. Otherwise emit a
        "recommended action" entry — the human (or autonomous
        controller) can use it.
        """
        plan: Optional[Plan] = ctx.perception.get("plan")
        if plan is None or not plan.steps:
            return

        first_step = plan.steps[0]
        description = getattr(first_step, "description", str(first_step))

        # Try to find a matching skill
        skill_invoked = False
        if self.skill_registry is not None:
            try:
                # Look for any validated skill whose name appears in
                # the step description
                for skill in self.skill_registry.list_skills(state="validated"):
                    if skill.name and skill.name.lower() in description.lower():
                        try:
                            result = self.skill_registry.invoke(
                                skill.name, ctx.perception,
                            )
                            report.actions_taken.append({
                                "kind": "skill",
                                "skill": skill.name,
                                "result": result,
                            })
                            skill_invoked = True
                            break
                        except (SkillNotFound, SkillNotInvocable):
                            continue
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"act (skill): {exc}")

        if not skill_invoked:
            report.actions_taken.append({
                "kind": "recommendation",
                "description": description,
                "reason": "no matching validated skill",
            })

    # ── Phase 8: LEARN ────────────────────────────────────────

    def _phase_learn(self, ctx: CycleContext, report: CycleReport) -> None:
        """Record cycle outcomes back into SelfModel."""
        if self.self_model is None:
            return
        try:
            updates = self.self_model.ingest_cycle_result(report.to_dict())
            report.learning_updates = updates
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"learn: {exc}")

    # ── Phase 9: CONSOLIDATE (every Nth cycle) ────────────────

    def _phase_consolidate(self, ctx: CycleContext, report: CycleReport) -> None:
        """Run Consolidation periodically."""
        if self.consolidation is None:
            return
        if ctx.cycle_number % self._consolidate_every_n != 0:
            return
        try:
            self.consolidation.run()
            report.consolidation_ran = True
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"consolidate: {exc}")


# ── Convenience builder ──────────────────────────────────────


def build_default_mind(*, memory: Any = None) -> Mind:
    """Construct a Mind wired up with default singletons.

    Useful for one-line bootstrapping in scripts and the CLI:

        mind = build_default_mind()
        report = mind.run_cycle()
    """
    from core.cognitive.consolidation import get_consolidation
    from core.cognitive.curiosity import get_curiosity
    from core.cognitive.goals import get_goal_manager
    from core.cognitive.imagination import get_imagination
    from core.cognitive.planner import get_planner
    from core.cognitive.reflection import get_reflection
    from core.cognitive.self_model import get_self_model
    from core.cognitive.skill_registry import get_skill_registry
    from core.cognitive.theory_of_mind import get_theory_of_mind

    sm = get_self_model()
    gm = get_goal_manager()

    if memory is None:
        try:
            from core.memory.intelligence import MemoryIntelligence
            memory = MemoryIntelligence()
        except Exception:  # noqa: BLE001
            memory = None

    return Mind(
        self_model=sm,
        goal_manager=gm,
        reflection=get_reflection(memory=memory, self_model=sm, goal_manager=gm),
        planner=get_planner(),
        imagination=get_imagination(),
        curiosity=get_curiosity(),
        consolidation=get_consolidation(memory=memory) if memory else None,
        skill_registry=get_skill_registry(),
        theory_of_mind=get_theory_of_mind(),
        memory=memory,
    )


# ── Singleton accessor ────────────────────────────────────────


_instance: Optional[Mind] = None


def get_mind() -> Mind:
    """Lazily build and return the process-wide Mind instance."""
    global _instance
    if _instance is None:
        _instance = build_default_mind()
    return _instance
