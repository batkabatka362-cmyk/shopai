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
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from utils.logger import get_logger

from core.cognitive.consolidation import Consolidation
from core.cognitive.curiosity import Curiosity, CuriosityRecommendation
from core.cognitive.functions import (
    CognitiveDispatcher,
    CognitiveFunction,
    DispatchResult,
)
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
from core.mentality import Values

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
    # Wave 7c (GAP-15): per-phase error dict so the controller's
    # reflection synthesizer can mine failures at phase granularity
    # rather than treating the entire Mind cycle as one opaque blob.
    phase_errors: dict[str, str] = field(default_factory=dict)

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
            "phase_errors": dict(self.phase_errors),
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

    # How many recent cycle reports to keep in the in-memory journal
    # so the Mind can introspect its own behaviour over time.
    _CYCLE_HISTORY_SIZE = 50

    # Outcome statuses we treat as "skill succeeded" when calibrating
    # imagination predictions.
    _SUCCESS_STATUSES = frozenset({"ok", "success", "completed", "done"})

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
        values: Optional[Values] = None,
        consolidate_every_n: int = 10,
        cycle_history_size: Optional[int] = None,
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
        self.values = values

        self._cycle_count = 0
        self._consolidate_every_n = max(1, int(consolidate_every_n))
        self._cycle_history: deque[CycleReport] = deque(
            maxlen=int(cycle_history_size or self._CYCLE_HISTORY_SIZE),
        )
        # Latest calibration scores (None until first calibrated cycle)
        self._last_imagination_calibration: Optional[float] = None
        self._last_prediction_calibration: Optional[float] = None
        # Per-goal "strike" counters used by the lifecycle phase to
        # decide when to progress, complete, fail, or abandon a goal.
        # Shape: {goal_id: {"abstain": n, "skill_fail": n, "successes": n}}
        self._goal_strikes: dict[str, dict[str, int]] = {}

        # Wave 2 #7: cognitive function dispatch over the subsystems
        # wired above. Built lazily on first access so tests that
        # swap subsystems post-construction still see a live map.
        self._cognitive_dispatcher: Optional[CognitiveDispatcher] = None

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

        # Wave 7c (GAP-15): run each phase independently so a
        # failure in one doesn't skip all subsequent phases and the
        # per-phase error dict fills with granular failure info for
        # the reflection synthesizer to mine.
        _phases = [
            ("calibrate",      self._phase_calibrate),
            ("perceive",       self._phase_perceive),
            ("reflect",        self._phase_reflect),
            ("set_goals",      self._phase_set_goals),
            ("plan",           self._phase_plan),
            ("imagine",        self._phase_imagine),
            ("predict",        self._phase_predict),
            ("act",            self._phase_act),
            ("learn",          self._phase_learn),
            ("goal_lifecycle", self._phase_goal_lifecycle),
            ("consolidate",    self._phase_consolidate),
        ]
        for phase_name, phase_fn in _phases:
            try:
                phase_fn(ctx, report)
            except Exception as exc:  # noqa: BLE001
                err_str = f"{type(exc).__name__}: {exc}"
                report.phase_errors[phase_name] = err_str
                logger.warning(
                    "Mind cycle %d phase %s failed: %s",
                    ctx.cycle_number, phase_name, err_str,
                )
        # Backward compat: set aggregate error if any phase failed
        if report.phase_errors:
            report.error = "; ".join(
                f"{k}: {v}" for k, v in report.phase_errors.items()
            )

        # Wave 4 #4: post-cycle cognitive audit — dispatch the
        # side-effect-free introspection functions so every cycle
        # leaves an observability trace on the dispatcher. Si
        # snapshots the self-model and Ni asks consolidation what
        # it would do in dry-run mode. Both are cheap and
        # idempotent; failures are captured on the DispatchResult,
        # never raised.
        self._emit_cognitive_audit(ctx)

        report.finished_at = time.time()
        self._cycle_history.append(report)
        logger.info("Mind cycle %d: %s", ctx.cycle_number, report.headline())
        return report

    def _emit_cognitive_audit(self, ctx: CycleContext) -> None:
        """Run the post-cycle observability dispatch pass.

        Separated from :meth:`run_cycle` so tests / subclasses can
        skip or override it. Wraps the two introspection calls in
        a single try/except — an exception here must never
        propagate into the cycle result.
        """
        try:
            disp = self.cognitive_dispatcher()
            audit_ctx = {"dry_run": True, "cycle": ctx.cycle_number}
            disp.dispatch(CognitiveFunction.Si, audit_ctx)
            disp.dispatch(CognitiveFunction.Ni, audit_ctx)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cognitive audit emit failed: %s", exc)

    def cognitive_report(self) -> dict[str, Any]:
        """Return the dispatcher's observability snapshot.

        Convenience wrapper over
        :meth:`CognitiveDispatcher.stats` that also includes the
        list of registered functions and the total cycle count
        for correlation (""N dispatches across M cycles"").
        """
        stats = self.cognitive_dispatcher().stats()
        stats["cycles_run"] = self._cycle_count
        return stats

    # ── Cognitive function dispatch (Wave 2 #7 integration) ──

    def cognitive_dispatcher(self) -> CognitiveDispatcher:
        """Return (building on first call) the cognitive function dispatcher.

        Rather than using :meth:`CognitiveDispatcher.default_for_mind`
        — which assumes generic ``analyse``/``plan``/``predict``
        method names — we wire handlers directly against the real
        subsystem APIs attached to this Mind. Missing subsystems are
        silently skipped so a stripped-down Mind still gets a usable
        dispatcher for whichever tools it has.

        The mapping:

        * ``Ti`` (Introverted Thinking) → :meth:`Reflection.reflect`
          in dry-run mode (``apply=False``) so a Ti dispatch is a
          pure inspection call with no side effects
        * ``Te`` (Extroverted Thinking) → :meth:`Planner.plan` with
          the context passed straight through
        * ``Ne`` (Extroverted Intuition) → :meth:`Curiosity.recommend`
          (ignores the context — curiosity reads its own state)
        * ``Ni`` (Introverted Intuition) → :meth:`Consolidation.run`
          in dry-run mode so Ni is idempotent and safe to call for
          "what would consolidate say?" queries
        * ``Si`` (Introverted Sensing) → :meth:`SelfModel.snapshot`
        * ``Se`` (Extroverted Sensing) → the Mind's own perceive
          hook (``self.perceive(context)``) if one is attached by a
          subclass, otherwise skipped
        * ``Fi`` (Introverted Feeling) → :meth:`Values.score` when
          an operator Values object was injected, otherwise skipped
        * ``Fe`` (Extroverted Feeling) → :meth:`TheoryOfMind.predict_response`
          bridged onto the dispatcher's (ctx) signature by reading
          ``agent`` and ``action`` out of the context dict
        """
        if self._cognitive_dispatcher is None:
            self._cognitive_dispatcher = self._build_cognitive_dispatcher()
        return self._cognitive_dispatcher

    def _build_cognitive_dispatcher(self) -> CognitiveDispatcher:
        disp = CognitiveDispatcher()

        ref = self.reflection
        if ref is not None and hasattr(ref, "reflect"):
            def _ti(ctx: dict[str, Any]) -> Any:
                limit = int(ctx.get("episode_limit", 100))
                category = str(ctx.get("category", ""))
                return ref.reflect(
                    episode_limit=limit,
                    category=category,
                    apply=False,
                )
            disp.register(CognitiveFunction.Ti, _ti)

        plan = self.planner
        if plan is not None and hasattr(plan, "plan"):
            def _te(ctx: dict[str, Any]) -> Any:
                goal = ctx.get("goal")
                if goal is None:
                    return None
                return plan.plan(goal, context=ctx)
            disp.register(CognitiveFunction.Te, _te)

        cur = self.curiosity
        if cur is not None and hasattr(cur, "recommend"):
            disp.register(
                CognitiveFunction.Ne,
                lambda ctx: cur.recommend(),
            )

        con = self.consolidation
        if con is not None and hasattr(con, "run"):
            def _ni(ctx: dict[str, Any]) -> Any:
                return con.run(dry_run=bool(ctx.get("dry_run", True)))
            disp.register(CognitiveFunction.Ni, _ni)

        sm = self.self_model
        if sm is not None and hasattr(sm, "snapshot"):
            disp.register(
                CognitiveFunction.Si,
                lambda ctx: sm.snapshot(),
            )

        # Se: Mind doesn't expose a public perceive() by default. A
        # subclass (or tests) can attach one to pick up Se dispatch.
        if hasattr(self, "perceive") and callable(getattr(self, "perceive")):
            disp.register(
                CognitiveFunction.Se,
                lambda ctx: self.perceive(ctx),  # type: ignore[attr-defined]
            )

        values = self.values
        if values is not None and hasattr(values, "score"):
            disp.register(
                CognitiveFunction.Fi,
                lambda ctx: values.score(ctx),
            )

        tom = self.theory_of_mind
        if tom is not None and hasattr(tom, "predict_response"):
            def _fe(ctx: dict[str, Any]) -> Any:
                agent = ctx.get("agent") or ctx.get("agent_id")
                action = ctx.get("action")
                if not agent or not action:
                    return None
                return tom.predict_response(str(agent), str(action))
            disp.register(CognitiveFunction.Fe, _fe)

        return disp

    def dispatch_cognitive(
        self,
        function: CognitiveFunction,
        context: Optional[dict[str, Any]] = None,
    ) -> DispatchResult:
        """Run a single cognitive function through the dispatcher.

        Thin convenience: call ``dispatch_cognitive(Ti, {...})``
        instead of ``cognitive_dispatcher().dispatch(Ti, {...})``.
        Returns the full :class:`DispatchResult` so callers can
        distinguish ``ok``/``skipped``/``error``.
        """
        return self.cognitive_dispatcher().dispatch(function, context)

    def active_cognitive_functions(self) -> list[CognitiveFunction]:
        """Return the subset of cognitive functions currently wired."""
        return self.cognitive_dispatcher().registered()

    def cycle_count(self) -> int:
        return self._cycle_count

    def last_cycles(self, n: int = 10) -> list[CycleReport]:
        """Return the most-recent ``n`` cycle reports (newest last)."""
        if n <= 0:
            return []
        return list(self._cycle_history)[-n:]

    def previous_cycle(self) -> Optional[CycleReport]:
        """Return the report of the cycle that ran just before the
        current one, or None if no previous cycle exists."""
        return self._cycle_history[-1] if self._cycle_history else None

    def calibration_snapshot(self) -> dict[str, Any]:
        """Compact snapshot of the Mind's most recent self-calibration.

        Returns the latest imagination/prediction calibration scores
        (0–1 where 1 = perfect) plus a small running summary so the
        CLI / status dashboards can render trust signals."""
        history = list(self._cycle_history)
        cycles_with_imagined = sum(1 for r in history if r.imagined_plan is not None)
        return {
            "history_size": len(history),
            "cycles_with_imagination": cycles_with_imagined,
            "last_imagination_calibration": self._last_imagination_calibration,
            "last_prediction_calibration": self._last_prediction_calibration,
        }

    # ── Phase 0: CALIBRATE (cross-cycle self-evaluation) ─────

    def _phase_calibrate(self, ctx: CycleContext, report: CycleReport) -> None:
        """Score the *previous* cycle's predictions against what
        actually happened, and feed that score back into SelfModel.

        This is the loop that lets the Mind learn whether its own
        modules are trustworthy:

          - Imagination predicted ``expected_score`` for a plan, then
            we acted (or abstained). If we ran skills, we can compare
            the score against the realized success rate.
          - TheoryOfMind predicted reactions; if we observed those
            reactions in the next cycle's reflection lessons, the
            prediction was good.

        Calibration scores land in SelfModel as ``mind.imagination_
        calibration`` and ``mind.prediction_calibration``. Because
        SelfModel weakness/gap detection is what GoalManager.propose_
        from_self_model uses, a chronically miscalibrated Mind will
        spontaneously generate goals to improve its own predictions.
        """
        prev = self.previous_cycle()
        if prev is None:
            return

        # ── Imagination calibration ──
        cal = self._calibrate_imagination(prev)
        if cal is not None:
            self._last_imagination_calibration = cal
            report.notes.append(
                f"calibrate: imagination={cal:.2f}"
            )
            if self.self_model is not None:
                try:
                    self.self_model.assess(
                        "mind.imagination_calibration",
                        cal,
                        source="mind.calibration",
                        notes=(
                            f"imagined={float(prev.imagined_plan.expected_score):.2f}"
                            if prev.imagined_plan else ""
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    report.notes.append(f"calibrate (assess imagination): {exc}")

        # ── Prediction calibration ──
        pcal = self._calibrate_predictions(prev)
        if pcal is not None:
            self._last_prediction_calibration = pcal
            report.notes.append(
                f"calibrate: prediction={pcal:.2f}"
            )
            if self.self_model is not None:
                try:
                    self.self_model.assess(
                        "mind.prediction_calibration",
                        pcal,
                        source="mind.calibration",
                    )
                except Exception as exc:  # noqa: BLE001
                    report.notes.append(f"calibrate (assess prediction): {exc}")

    def _calibrate_imagination(self, prev: CycleReport) -> Optional[float]:
        """Compare last cycle's imagined score against realized skill
        outcomes. Returns a 0–1 score (1 = perfect prediction) or
        None when no ground truth is available."""
        imagined = prev.imagined_plan
        if imagined is None:
            return None

        # Pick out skill executions — they're the only actions that
        # carry an objective success/failure signal.
        skill_actions = [
            a for a in prev.actions_taken
            if a.get("kind") == "skill"
        ]

        if skill_actions:
            successes = 0
            for a in skill_actions:
                result = a.get("result") or {}
                status = str(result.get("status", "")).lower()
                if status in self._SUCCESS_STATUSES:
                    successes += 1
            success_rate = successes / len(skill_actions)
            imagined_score = float(getattr(imagined, "expected_score", 0.0) or 0.0)
            error = abs(imagined_score - success_rate)
            return max(0.0, min(1.0, 1.0 - error))

        # If we abstained AND imagination was the reason, that's a
        # vacuous "correct" — the gate trusted imagination but no
        # ground truth materialized. Reward modestly so calibration
        # doesn't sit at None forever in cautious modes, but flag
        # as "unverified" by capping at 0.6.
        abstained = any(
            a.get("kind") == "abstain" for a in prev.actions_taken
        )
        if abstained:
            return 0.6

        return None

    def _calibrate_predictions(self, prev: CycleReport) -> Optional[float]:
        """Score TheoryOfMind predictions from the previous cycle.

        Heuristic: if any high-confidence prediction caused a pause
        and we did NOT subsequently observe a regression lesson on
        the same subject in this cycle's reflection, the prediction
        was likely a false alarm. If skill actions ran successfully
        despite confident predictions, the predictions were either
        positive or noise — both fine.
        """
        if not prev.predictions:
            return None

        paused = [
            a for a in prev.actions_taken
            if a.get("kind") == "pause"
        ]
        skill_actions = [
            a for a in prev.actions_taken if a.get("kind") == "skill"
        ]

        if paused and not skill_actions:
            # The prediction prevented action; without ground truth
            # we can't fully verify, but we credit modestly.
            return 0.55

        if skill_actions:
            successes = sum(
                1 for a in skill_actions
                if str((a.get("result") or {}).get("status", "")).lower()
                in self._SUCCESS_STATUSES
            )
            success_rate = successes / len(skill_actions)
            # If predictions were ignored (no pause) and skills
            # succeeded → predictions were correctly low-impact.
            return max(0.0, min(1.0, success_rate))

        return None

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

    # Deliberation thresholds — the Mind refuses to act when its own
    # imagination/prediction modules are pessimistic. Tunable, but
    # the defaults match "act only when at least one signal is
    # weakly positive and nothing is loudly negative".
    _ABSTAIN_SCORE_THRESHOLD = 0.30
    _ABSTAIN_CONFIDENCE_THRESHOLD = 0.30
    _PREDICTION_PAUSE_CONFIDENCE = 0.60
    _NEGATIVE_REACTION_KEYWORDS = (
        "reject", "refuse", "decline", "complain", "angry",
        "negative", "dissatisfied", "oppose", "escalate",
        "churn", "abandon", "block", "hostile",
    )

    def _phase_act(self, ctx: CycleContext, report: CycleReport) -> None:
        """Either invoke a matching Skill or record a recommendation.

        We look for a validated skill whose name matches the goal's
        first plan step. If found, invoke it. Otherwise emit a
        "recommended action" entry — the human (or autonomous
        controller) can use it.

        Before any of that, a *deliberation gate* checks the
        outputs of the imagination + prediction phases:

          1. If the Imagination scored the plan badly (low expected
             score *or* low confidence), we abstain — acting on a
             plan we don't believe in is worse than waiting.
          2. If TheoryOfMind predicted a high-confidence negative
             reaction, we pause and surface a "review predictions"
             recommendation rather than executing.
        """
        plan: Optional[Plan] = ctx.perception.get("plan")
        if plan is None or not plan.steps:
            return

        first_step = plan.steps[0]
        description = getattr(first_step, "description", str(first_step))

        # ── Deliberation gate ─────────────────────────────────
        if self._deliberation_blocks_action(ctx, report, description):
            return

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

    def _deliberation_blocks_action(
        self,
        ctx: CycleContext,
        report: CycleReport,
        description: str,
    ) -> bool:
        """Return True (and record an abstain/pause action) when the
        Mind's imagination or prediction modules say "don't act"."""
        # 1. Imagination pessimism → abstain.
        imagined = report.imagined_plan
        if imagined is not None:
            score = float(getattr(imagined, "expected_score", 0.0) or 0.0)
            conf = float(getattr(imagined, "overall_confidence", 0.0) or 0.0)
            if (score < self._ABSTAIN_SCORE_THRESHOLD
                    or conf < self._ABSTAIN_CONFIDENCE_THRESHOLD):
                report.actions_taken.append({
                    "kind": "abstain",
                    "description": description,
                    "reason": (
                        f"imagination pessimistic "
                        f"(score={score:.2f}, confidence={conf:.2f})"
                    ),
                    "expected_score": round(score, 3),
                    "overall_confidence": round(conf, 3),
                })
                report.notes.append(
                    f"act: abstained (imagined score={score:.2f},"
                    f" conf={conf:.2f})"
                )
                return True

        # 2. Confidently-predicted negative reaction → pause.
        for pred in report.predictions:
            try:
                conf = float(getattr(pred, "confidence", 0.0) or 0.0)
                response = (
                    getattr(pred, "predicted_response", "") or ""
                ).lower()
                agent_id = getattr(pred, "agent_id", "")
            except Exception:  # noqa: BLE001
                continue
            if conf < self._PREDICTION_PAUSE_CONFIDENCE:
                continue
            if not any(kw in response for kw in self._NEGATIVE_REACTION_KEYWORDS):
                continue
            report.actions_taken.append({
                "kind": "pause",
                "description": description,
                "reason": (
                    f"agent {agent_id} predicted to react negatively "
                    f"({response[:60]!r}, conf={conf:.2f})"
                ),
                "agent_id": agent_id,
                "predicted_response": response[:120],
                "prediction_confidence": round(conf, 3),
            })
            report.notes.append(
                f"act: paused on predicted reaction from {agent_id}"
            )
            return True

        return False

    # ── Phase 8: LEARN ────────────────────────────────────────

    def _phase_learn(self, ctx: CycleContext, report: CycleReport) -> None:
        """Record cycle outcomes back into SelfModel + memory.

        Three paths run independently:
          1. Format the cycle as a controller-style result and let
             SelfModel.ingest_cycle_result extract phase/engine
             signals from it.
          2. Record cognitive-level signals directly via assess()
             so the SelfModel grows with every cycle.
          3. Persist a structured episode to MemoryIntelligence so
             Reflection has data to reflect on.

        Each path is independent — memory persistence is not gated
        on having a SelfModel, and SelfModel updates are not gated
        on having a memory backend.
        """
        updates = 0
        if self.self_model is not None:
            updates += self._learn_into_self_model(report)
        if self._record_cycle_episode(report):
            updates += 1
        report.learning_updates = updates

    def _learn_into_self_model(self, report: CycleReport) -> int:
        """SelfModel-only side of LEARN. Returns the number of
        capability updates applied."""
        updates = 0
        try:
            # Path 1: feed the controller-style fields that
            # ingest_cycle_result understands. The Mind's report
            # uses different keys, so we synthesize a minimal cycle
            # dict with the bits SelfModel knows how to parse.
            synthetic = {
                "status": "success" if not report.error else "error",
                "phases": {},
                "executions": [
                    {"engine": a.get("skill", "unknown"),
                     "status": a.get("result", {}).get("status", "ok")}
                    for a in report.actions_taken
                    if a.get("kind") == "skill"
                ],
                "error": report.error,
            }
            updates = self.self_model.ingest_cycle_result(synthetic)
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"learn (ingest): {exc}")

        # Path 2: cognitive-level assessments — always recorded.
        try:
            self.self_model.assess(
                "mind.cycle_duration",
                # Score: under 1s = perfect, over 30s = bad
                max(0.0, min(1.0, 1.0 - (report.duration_s() - 1.0) / 29.0)),
                source="mind",
                notes=f"duration={report.duration_s():.2f}s",
            )
            updates += 1
            if report.plan is not None:
                self.self_model.assess(
                    "mind.planning",
                    min(1.0, report.plan.step_count() / 6.0),
                    source="mind",
                    notes=f"steps={report.plan.step_count()}",
                )
                updates += 1
            if report.imagined_plan is not None:
                self.self_model.assess(
                    "mind.imagination_quality",
                    float(report.imagined_plan.overall_confidence),
                    source="mind",
                )
                updates += 1
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"learn (assess): {exc}")

        return updates

    # Map the highest-priority action kind to a 1-5 score for the
    # episode log. Used by `_record_cycle_episode`.
    _ACTION_KIND_SCORES = {
        "skill": 4.0,           # we executed something — neutral-good baseline
        "recommendation": 3.0,  # produced advice but didn't act
        "abstain": 2.0,         # imagination said no
        "pause": 2.0,           # prediction said wait
    }

    def _record_cycle_episode(self, report: CycleReport) -> bool:
        """Persist a structured episode of this cycle to memory.

        Returns True iff a memory was written. Silently no-ops when
        no memory backend is wired or when the call fails — Mind
        must never crash because the journal is unavailable.
        """
        if self.memory is None:
            return False
        create = getattr(self.memory, "create", None)
        if not callable(create):
            return False

        # Pick the dominant action kind for this cycle so the
        # episode score reflects what actually happened.
        kind = ""
        result_status = ""
        for a in report.actions_taken:
            kind = a.get("kind", "") or kind
            r = a.get("result") or {}
            if isinstance(r, dict):
                result_status = str(r.get("status", "") or result_status)
            if kind == "skill":
                break  # skill outcomes always win

        score = self._ACTION_KIND_SCORES.get(kind, 3.0)
        # Refine skill score by realized success status.
        if kind == "skill":
            if result_status.lower() in self._SUCCESS_STATUSES:
                score = 4.5
            elif result_status:
                score = 1.5  # explicit failure status

        if report.error:
            score = 1.0

        action_label = (
            f"mind.cycle.{kind}" if kind else "mind.cycle"
        )

        content = {
            "cycle_number": report.cycle_number,
            "duration_s": round(report.duration_s(), 3),
            "selected_goal_id": report.selected_goal_id or "",
            "goals_proposed": list(report.goals_proposed),
            "actions": [
                {
                    "kind": a.get("kind", ""),
                    "skill": a.get("skill", ""),
                    "reason": a.get("reason", ""),
                }
                for a in report.actions_taken
            ],
            "imagined_score": (
                round(float(report.imagined_plan.expected_score), 3)
                if report.imagined_plan else None
            ),
            "imagined_confidence": (
                round(float(report.imagined_plan.overall_confidence), 3)
                if report.imagined_plan else None
            ),
            "predictions": len(report.predictions),
            "error": report.error or "",
        }
        result = {
            "actions_taken": len(report.actions_taken),
            "goals_proposed": len(report.goals_proposed),
            "consolidation_ran": report.consolidation_ran,
            "status": result_status or ("error" if report.error else "ok"),
        }
        try:
            create(
                category="mind",
                content=content,
                action=action_label,
                result=result,
                score=score,
                memory_type="episodic",
                tags=["mind", "cycle", kind] if kind else ["mind", "cycle"],
            )
            return True
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"learn (memory.create): {exc}")
            return False

    # ── Phase 8.5: GOAL LIFECYCLE ─────────────────────────────

    # How much progress one successful skill execution adds to the
    # active goal. 0.25 → goal completes after 4 clean cycles.
    _GOAL_PROGRESS_STEP = 0.25
    # Strike thresholds before retiring a goal.
    _GOAL_ABSTAIN_STRIKES = 3
    _GOAL_FAIL_STRIKES = 3

    def _phase_goal_lifecycle(
        self, ctx: CycleContext, report: CycleReport,
    ) -> None:
        """Advance, complete, fail, or abandon the goal we just
        worked on this cycle.

        Without this phase, goals proposed by Reflection / Curiosity /
        SelfModel never reach a terminal state — the goal pool grows
        forever and `pick_next` keeps revisiting old work. The Mind
        looks busy but never finishes anything.

        The lifecycle rules are intentionally conservative:

          - A successful skill execution bumps progress by
            ``_GOAL_PROGRESS_STEP``. When progress hits 1.0, the goal
            is **completed** and its strike counters cleared.
          - Three consecutive cycles where the deliberation gate
            **abstained** on this goal → ``abandon`` (the Mind doesn't
            believe in this goal any more).
          - Three consecutive cycles with **failed skill executions**
            → ``fail`` (we tried and it didn't work).
          - Pauses and recommendations are neutral — they neither
            advance progress nor accumulate strikes.
          - Any successful execution resets the failure strike count.
        """
        if self.goal_manager is None:
            return
        gid = report.selected_goal_id
        if not gid:
            return

        strikes = self._goal_strikes.setdefault(
            gid, {"abstain": 0, "skill_fail": 0, "successes": 0},
        )

        skill_actions = [
            a for a in report.actions_taken if a.get("kind") == "skill"
        ]
        abstained = any(
            a.get("kind") == "abstain" for a in report.actions_taken
        )

        # ── Successful execution: progress + maybe complete ──
        if skill_actions:
            all_ok = all(
                str((a.get("result") or {}).get("status", "")).lower()
                in self._SUCCESS_STATUSES
                for a in skill_actions
            )
            if all_ok:
                strikes["successes"] += 1
                strikes["skill_fail"] = 0
                strikes["abstain"] = 0
                if self._advance_goal_progress(gid, report):
                    return  # goal completed → state cleared inside helper
                return
            # At least one skill failed
            strikes["skill_fail"] += 1
        elif abstained:
            strikes["abstain"] += 1

        # ── Strike-out → retire the goal ──
        if strikes["abstain"] >= self._GOAL_ABSTAIN_STRIKES:
            self._retire_goal(
                gid, "abandon",
                f"{strikes['abstain']} consecutive abstains: imagination pessimistic",
                report,
            )
            return
        if strikes["skill_fail"] >= self._GOAL_FAIL_STRIKES:
            self._retire_goal(
                gid, "fail",
                f"{strikes['skill_fail']} consecutive skill failures",
                report,
            )

    def _advance_goal_progress(
        self, gid: str, report: CycleReport,
    ) -> bool:
        """Bump goal progress; complete + clear strikes when done.

        Returns True iff the goal was completed in this call."""
        try:
            current = self.goal_manager.get(gid) or {}
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"goal_lifecycle (get): {exc}")
            return False
        new_progress = min(
            1.0,
            float(current.get("progress", 0.0)) + self._GOAL_PROGRESS_STEP,
        )
        try:
            self.goal_manager.update_progress(
                gid, new_progress, notes="mind: skill success",
            )
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"goal_lifecycle (progress): {exc}")
            return False

        if new_progress >= 1.0:
            try:
                self.goal_manager.complete(
                    gid,
                    result_notes=(
                        f"after {self._goal_strikes[gid]['successes']} "
                        "successful execution(s)"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"goal_lifecycle (complete): {exc}")
                return False
            report.notes.append(f"goal_lifecycle: completed {gid[:14]}")
            self._goal_strikes.pop(gid, None)
            return True

        report.notes.append(
            f"goal_lifecycle: progress {new_progress:.2f} on {gid[:14]}"
        )
        return False

    def _retire_goal(
        self, gid: str, mode: str, reason: str, report: CycleReport,
    ) -> None:
        """Move a goal to a terminal state via abandon/fail."""
        try:
            if mode == "abandon":
                self.goal_manager.abandon(gid, reason=reason)
            elif mode == "fail":
                self.goal_manager.fail(gid, reason=reason)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"goal_lifecycle ({mode}): {exc}")
            return
        report.notes.append(
            f"goal_lifecycle: {mode}ed {gid[:14]} ({reason})"
        )
        self._goal_strikes.pop(gid, None)

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
