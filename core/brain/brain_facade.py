"""Brain facade — single API over 91 subsystems.

Twelve sprints produced a rich brain but its API surface is
fragmented: callers must know about reward_model(), world_model(),
coverage_engine(), router(), monologue(), habit(), policy_library(),
and another 80-odd singletons. That coupling makes every caller
brittle — refactors ripple outward, integration tests need
dozens of imports.

BrainFacade is the one entry point. ``brain()`` returns a thin
wrapper that:

  • Exposes *think()*       — one-shot decision given an observation.
  • Exposes *learn()*       — fold outcome events via OutcomeRouter.
  • Exposes *introspect()*  — structured status snapshot.
  • Exposes *explain()*     — 'why' answer over the last decision.
  • Exposes *housekeep()*   — run the daily maintenance pass.

Each method fans to the correct subsystem. No new algorithms; the
value is in making the API tractable and letting call sites depend
on *one* import instead of a dozen. Dependencies are lazy so a
missing subsystem doesn't break the facade.

Pure orchestration. Zero LLM.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.facade")


@dataclass
class Snapshot:
    """Single-shot introspection across every connected subsystem."""
    ts: float = 0.0
    world_model: dict[str, Any] = field(default_factory=dict)
    epistemic: dict[str, Any] = field(default_factory=dict)
    hypothesis: dict[str, Any] = field(default_factory=dict)
    reward: dict[str, Any] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    habits: dict[str, Any] = field(default_factory=dict)
    trust: list[dict[str, Any]] = field(default_factory=list)
    self_improvement: dict[str, Any] = field(default_factory=dict)
    surprise: dict[str, Any] = field(default_factory=dict)
    regret: dict[str, Any] = field(default_factory=dict)
    commitments: dict[str, Any] = field(default_factory=dict)
    learning: list[dict[str, Any]] = field(default_factory=list)
    cases: dict[str, Any] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    competence: dict[str, Any] = field(default_factory=dict)
    curiosity: dict[str, Any] = field(default_factory=dict)
    drift: dict[str, Any] = field(default_factory=dict)
    goals: dict[str, Any] = field(default_factory=dict)
    attention: dict[str, Any] = field(default_factory=dict)
    owner: dict[str, Any] = field(default_factory=dict)
    experiments: dict[str, Any] = field(default_factory=dict)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    uplift: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "world_model": self.world_model,
            "epistemic": self.epistemic,
            "hypothesis": self.hypothesis,
            "reward": self.reward,
            "policies": self.policies,
            "habits": self.habits,
            "trust": self.trust,
            "self_improvement": self.self_improvement,
            "surprise": self.surprise,
            "regret": self.regret,
            "commitments": self.commitments,
            "learning": self.learning,
            "cases": self.cases,
            "skills": self.skills,
            "competence": self.competence,
            "curiosity": self.curiosity,
            "drift": self.drift,
            "goals": self.goals,
            "attention": self.attention,
            "owner": self.owner,
            "experiments": self.experiments,
            "budgets": self.budgets,
            "knowledge": self.knowledge,
            "uplift": self.uplift,
        }


# ── Facade ──────────────────────────────────────────────────

class BrainFacade:
    def __init__(self) -> None:
        self._last_cycle_report: Any = None
        self._last_decision: Any = None

    # ── think ──────────────────────────────────────────────

    def think(
        self,
        observation: dict[str, Any],
        candidate_action: dict[str, Any] | None = None,
        *,
        stakes: float = 0.3,
        confidence: float = 0.6,
        urgency: int = 0,
        skip: tuple[str, ...] = (),
        governor: Any | None = None,
    ) -> dict[str, Any]:
        """Run one AGI cycle and return the structured report."""
        try:
            from core.brain.agi_cycle import run_cycle
        except Exception:
            return {"status": "no_cycle_module"}
        report = run_cycle(
            observation=observation,
            candidate_action=candidate_action,
            stakes=stakes, confidence=confidence, urgency=urgency,
            skip=skip, governor=governor,
        )
        self._last_cycle_report = report
        if report.chosen_action:
            self._last_decision = report
        return report.as_dict()

    # ── learn ──────────────────────────────────────────────

    def learn(
        self,
        kind: str,
        features: dict[str, Any] | None = None,
        **outcome_fields: Any,
    ) -> dict[str, Any]:
        """Emit one Outcome to the router for fan-out learning."""
        try:
            from core.brain.outcome_router import Outcome, router
        except Exception:
            return {"status": "no_router"}
        oc = Outcome(
            kind=kind,
            features=dict(features or {}),
            **outcome_fields,
        )
        return router().emit(oc).as_dict()

    # ── introspect ─────────────────────────────────────────

    def introspect(self) -> Snapshot:
        snap = Snapshot(ts=time.time())
        # Each lazy-fetch is wrapped so one missing subsystem doesn't
        # block the rest.
        def _safe(fn):
            try:
                return fn()
            except Exception:
                return {}

        snap.world_model = _safe(lambda: _wm_summary())
        snap.epistemic = _safe(lambda: _ep_summary())
        snap.hypothesis = _safe(lambda: _hypo_summary())
        snap.reward = _safe(lambda: _reward_summary())
        snap.policies = _safe(lambda: _policy_summary())
        snap.habits = _safe(lambda: _habit_summary())
        snap.trust = _safe(lambda: _trust_top())
        snap.self_improvement = _safe(lambda: _si_summary())
        snap.surprise = _safe(lambda: _surprise_summary())
        snap.regret = _safe(lambda: _regret_summary())
        snap.commitments = _safe(lambda: _commitments_summary())
        snap.learning = _safe(lambda: _learning_summary())
        snap.cases = _safe(lambda: _case_base_summary())
        snap.skills = _safe(lambda: _skill_rank_summary())
        snap.competence = _safe(lambda: _competence_summary())
        snap.curiosity = _safe(lambda: _curiosity_summary())
        snap.drift = _safe(lambda: _drift_summary())
        snap.goals = _safe(lambda: _goal_summary())
        snap.attention = _safe(lambda: _attention_summary())
        snap.owner = _safe(lambda: _owner_summary())
        snap.experiments = _safe(lambda: _experiment_summary())
        snap.budgets = _safe(lambda: _budget_summary())
        snap.knowledge = _safe(lambda: _knowledge_summary())
        snap.uplift = _safe(lambda: _uplift_summary())
        return snap

    # ── v25: reasoning, safety, budget, experiments ──────

    def owner_weights(self) -> dict[str, float]:
        """Current owner preference weights for the utility blender."""
        try:
            return _owner_model().weights()
        except Exception as exc:
            logger.debug("owner_weights failed: %s", exc)
            return {}

    def record_owner_feedback(
        self,
        action_kind: str,
        approved: bool,
        *,
        cost_usd: float = 0.0,
        bold: bool = False,
        latency_s: float = 0.0,
    ) -> None:
        try:
            _owner_model().record(
                action_kind=action_kind, approved=approved,
                cost_usd=cost_usd, bold=bold, latency_s=latency_s,
            )
        except Exception as exc:
            logger.debug("record_owner_feedback failed: %s", exc)

    def safety_check(
        self,
        action: dict[str, Any],
        *,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Run the action safety guard: bright lines + blast + rollback."""
        try:
            return _safety_guard().evaluate(
                action, confidence=confidence,
            ).as_dict()
        except Exception as exc:
            logger.debug("safety_check failed: %s", exc)
            return {"verdict": "allow", "reasons": ["guard_unavailable"]}

    def reserve_budget(
        self, category: str, amount_usd: float,
    ) -> str | None:
        try:
            return _budget_ledger().reserve(
                category, amount_usd,
            ).id
        except Exception as exc:
            logger.debug("reserve_budget failed: %s", exc)
            return None

    def commit_budget(
        self,
        reservation_id: str,
        actual_amount: float | None = None,
    ) -> bool:
        try:
            _budget_ledger().commit(reservation_id, actual_amount)
            return True
        except Exception as exc:
            logger.debug("commit_budget failed: %s", exc)
            return False

    def release_budget(self, reservation_id: str) -> bool:
        try:
            _budget_ledger().release(reservation_id)
            return True
        except Exception:
            return False

    def allocate_experiment(
        self, name: str, unit_id: str,
    ) -> str:
        """Deterministically bucket a unit into a variant."""
        try:
            return _experiment_manager().allocate(name, unit_id)
        except Exception as exc:
            logger.debug("allocate_experiment failed: %s", exc)
            return ""

    def record_experiment_outcome(
        self, name: str, unit_id: str, outcome: float,
    ) -> None:
        try:
            _experiment_manager().observe(name, unit_id, outcome)
        except Exception as exc:
            logger.debug("record_experiment_outcome failed: %s", exc)

    def ate(
        self,
        *,
        treatment_value: str,
        control_value: str,
        outcome_key: str,
        covariates_subset: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Estimate the average treatment effect from experience."""
        try:
            return _uplift_estimator().ate(
                treatment_value=treatment_value,
                control_value=control_value,
                outcome_key=outcome_key,
                covariates_subset=covariates_subset,
            ).as_dict()
        except Exception as exc:
            logger.debug("ate failed: %s", exc)
            return {}

    def assert_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        is_literal: bool = False,
        confidence: float = 1.0,
        source: str = "",
    ) -> None:
        try:
            _knowledge_graph().assert_triple(
                subject, predicate, obj,
                is_literal=is_literal,
                confidence=confidence, source=source,
            )
        except Exception as exc:
            logger.debug("assert_fact failed: %s", exc)

    def is_a(self, subject: str, target_class: str) -> bool:
        try:
            return _knowledge_graph().is_a(subject, target_class)
        except Exception:
            return False

    # ── v23: planning & reasoning ─────────────────────────

    def add_goal(
        self,
        description: str,
        *,
        parent_id: str | None = None,
        due_at: float | None = None,
        weight: float = 1.0,
        tags: tuple[str, ...] = (),
    ) -> str | None:
        try:
            return _goal_graph().add(
                description, parent_id=parent_id,
                due_at=due_at, weight=weight, tags=tags,
            ).id
        except Exception as exc:
            logger.debug("add_goal failed: %s", exc)
            return None

    def advance_goal(
        self, goal_id: str, progress: float,
    ) -> dict[str, Any] | None:
        try:
            g = _goal_graph().advance(goal_id, progress)
            return g.as_dict() if g else None
        except Exception as exc:
            logger.debug("advance_goal failed: %s", exc)
            return None

    def frontier(self) -> list[dict[str, Any]]:
        """Actionable leaf goals right now."""
        try:
            return [g.as_dict() for g in _goal_graph().frontier()]
        except Exception:
            return []

    def plan(
        self,
        start: dict[str, Any],
        goal_state: dict[str, Any],
        actions: list[Any],
        *,
        max_expansions: int = 1_000,
    ) -> dict[str, Any] | None:
        """Thin wrapper over plan_search for decision-path callers."""
        try:
            from core.brain import plan_search as ps
            plan = ps.search(
                start=start,
                goal_fn=ps.predicate_goal(goal_state),
                actions=actions,
                heuristic=ps.delta_heuristic(goal_state),
                max_expansions=max_expansions,
            )
            return plan.as_dict() if plan else None
        except Exception as exc:
            logger.debug("plan failed: %s", exc)
            return None

    def rank_by_attention(
        self,
        events: list[dict[str, Any]],
        *, k: int = 5,
    ) -> list[dict[str, Any]]:
        """Score events by salience, return top-k."""
        try:
            return [
                s.as_dict()
                for s in _attention_filter().top_k(events, k=k)
            ]
        except Exception as exc:
            logger.debug("rank_by_attention failed: %s", exc)
            return []

    # ── v22: learning beyond outcomes ─────────────────────

    def recall_case(
        self,
        situation: dict[str, Any],
        *, k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find the top-k most similar past cases to a situation."""
        try:
            matches = _case_base().recall(situation, k=k)
            return [m.as_dict() for m in matches]
        except Exception as exc:
            logger.debug("recall_case failed: %s", exc)
            return []

    def record_case(
        self,
        situation: dict[str, Any],
        action: str,
        outcome_score: float,
        tags: tuple[str, ...] = (),
    ) -> str | None:
        try:
            return _case_base().add(
                situation=situation, action=action,
                outcome_score=outcome_score, tags=tags,
            )
        except Exception as exc:
            logger.debug("record_case failed: %s", exc)
            return None

    def assess_competence(
        self, task_class: str,
    ) -> dict[str, Any]:
        try:
            return _competence_model().competence(task_class).as_dict()
        except Exception as exc:
            logger.debug("assess_competence failed: %s", exc)
            return {}

    def should_defer(
        self,
        task_class: str,
        *, threshold: float = 0.6, min_support: int = 5,
    ) -> bool:
        try:
            return _competence_model().should_defer(
                task_class, threshold=threshold,
                min_support=min_support,
            )
        except Exception:
            return False

    def record_task_outcome(
        self,
        task_class: str,
        success: bool,
        stated_confidence: float | None = None,
    ) -> None:
        try:
            _competence_model().record(
                task_class, success=success,
                stated_confidence=stated_confidence,
            )
        except Exception as exc:
            logger.debug("record_task_outcome failed: %s", exc)

    def note_surprise(
        self,
        observation_id: str,
        predicted: float,
        actual: float,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Feed the curiosity engine a prediction error."""
        try:
            item = _curiosity_engine().note(
                observation_id=observation_id,
                predicted=predicted, actual=actual,
                context=context or {},
            )
            return item.as_dict() if item is not None else None
        except Exception as exc:
            logger.debug("note_surprise failed: %s", exc)
            return None

    def observe_feature(
        self,
        feature: str,
        value: Any,
        *, phase: str = "recent",
        kind: str = "numeric",
    ) -> None:
        """Feed the drift detector a feature observation."""
        try:
            d = _drift_detector()
            if kind == "categorical":
                d.observe_categorical(feature, str(value), phase=phase)
            else:
                d.observe_numeric(feature, float(value), phase=phase)
        except Exception as exc:
            logger.debug("observe_feature failed: %s", exc)

    # ── commit / keep-your-word ────────────────────────────

    def commit(
        self,
        promise: str,
        owner: str,
        due_at: float,
        *,
        fulfillment_test: Any | None = None,
    ) -> str | None:
        """Register a durable promise. Returns commitment id or None."""
        try:
            return _commitment_register().register(
                promise=promise, owner=owner, due_at=due_at,
                fulfillment_test=fulfillment_test,
            ).id
        except Exception:
            return None

    # ── track subsystem improvement rate ───────────────────

    def track(
        self,
        subsystem: str,
        metric: str,
        value: float,
        *,
        cycle: int | None = None,
    ) -> None:
        """Log a subsystem metric so learning_curve can spot drift."""
        try:
            _learning_tracker().record(
                subsystem, metric, value, cycle=cycle,
            )
        except Exception as exc:
            logger.debug("track(%s, %s) failed: %s", subsystem, metric, exc)

    # ── evidence gate ──────────────────────────────────────

    def evidence_ready(
        self,
        facts: list[dict[str, Any]],
        *,
        min_sources: int = 2,
        min_volume: float = 1.0,
    ) -> dict[str, Any]:
        """Ask: do we have enough to answer, or should we gather more?"""
        try:
            from core.brain.evidence_sufficiency import check
            return check(
                facts=facts,
                min_sources=min_sources,
                min_volume=min_volume,
            ).as_dict()
        except Exception:
            return {"verdict": "decide", "note": "module_unavailable"}

    # ── claim conflict check ───────────────────────────────

    def validate_claims(
        self, claims: list[Any],
    ) -> dict[str, Any]:
        """Run knowledge_validator over a batch of (subject, predicate,
        object, source, confidence) claims."""
        try:
            from core.memory.knowledge_validator import KnowledgeValidator
            return KnowledgeValidator().validate(claims).as_dict()
        except Exception:
            return {"conflicts": [], "claims_examined": 0}

    # ── explain ────────────────────────────────────────────

    def explain(
        self,
        decision_id: str | None = None,
        polisher: Any = None,
    ) -> dict[str, Any]:
        """Compose a 'why' answer for the last decision or an
        explicit id."""
        try:
            from core.brain.explanation_aggregator import aggregate
        except Exception:
            return {"status": "no_aggregator"}
        did = decision_id or (
            f"cycle:{int(self._last_cycle_report.started_at)}"
            if self._last_cycle_report else "unknown"
        )
        context: dict[str, Any] = {}
        verdict = ""
        chosen: dict[str, Any] | None = None
        if self._last_cycle_report:
            context = self._last_cycle_report.observation
            chosen = self._last_cycle_report.chosen_action
            if chosen:
                verdict = str(chosen.get("kind", ""))
        exp = aggregate(
            decision_id=did,
            context=context,
            chosen_action=chosen,
            verdict=verdict,
            polisher=polisher,
        )
        return exp.as_dict()

    # ── housekeep ──────────────────────────────────────────

    def housekeep(self) -> dict[str, Any]:
        try:
            from core.memory.data_housekeeper import DataHousekeeper
            return DataHousekeeper().run().as_dict()
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}


# ── Summary helpers (lazy imports inside) ───────────────────

def _wm_summary() -> dict[str, Any]:
    from core.brain.world_model import world_model
    return world_model().summary()


def _ep_summary() -> dict[str, Any]:
    from core.brain.epistemic import coverage_engine
    return coverage_engine().summary()


def _hypo_summary() -> dict[str, Any]:
    from core.brain.hypothesis import engine
    e = engine()
    return {
        "pending": len(e.list_pending()),
        "overdue": len(e.list_overdue()),
        "calibration_global": e.calibration().as_dict(),
    }


def _reward_summary() -> dict[str, Any]:
    from core.brain.reward_model import reward_model
    return reward_model().size()


def _policy_summary() -> dict[str, Any]:
    from core.brain.policy_library import PolicyLibrary
    return PolicyLibrary().stats()


def _habit_summary() -> dict[str, Any]:
    from core.brain.habit import HabitLayer
    return HabitLayer().stats()


def _trust_top() -> list[dict[str, Any]]:
    from core.brain.trust_calibrator import TrustCalibrator
    return [s.as_dict() for s in TrustCalibrator().rank(limit=5)]


def _si_summary() -> dict[str, Any]:
    from core.brain.self_improvement import SelfImprovementEngine
    return SelfImprovementEngine().stats()


def _surprise_summary() -> dict[str, Any]:
    from core.brain.surprise import surprise_detector
    return surprise_detector().summary()


def _regret_summary() -> dict[str, Any]:
    from core.brain.regret_minimizer import minimizer
    return minimizer().summary()


_COMMIT_REG: Any = None
_COMMIT_LOCK = threading.Lock()


def _commitment_register():
    """Lazy singleton so every caller goes to the same SQLite file."""
    global _COMMIT_REG
    if _COMMIT_REG is None:
        with _COMMIT_LOCK:
            if _COMMIT_REG is None:
                from core.brain.commitment_register import CommitmentRegister
                _COMMIT_REG = CommitmentRegister()
    return _COMMIT_REG


def _commitments_summary() -> dict[str, Any]:
    r = _commitment_register()
    pending = r.pending()
    urgent = r.urgent(hours_ahead=24.0)
    return {
        "pending": len(pending),
        "urgent_24h": len(urgent),
        "next_due_at": (
            min((c.due_at for c in pending), default=None)
            if pending else None
        ),
    }


_LEARNING_TRACKER: Any = None
_LEARNING_LOCK = threading.Lock()


def _learning_tracker():
    """Lazy singleton LearningCurveTracker instance so every subsystem
    writes to the same SQLite file."""
    global _LEARNING_TRACKER
    if _LEARNING_TRACKER is None:
        with _LEARNING_LOCK:
            if _LEARNING_TRACKER is None:
                from core.brain.learning_curve import LearningCurveTracker
                _LEARNING_TRACKER = LearningCurveTracker()
    return _LEARNING_TRACKER


def _learning_summary() -> list[dict[str, Any]]:
    from core.brain.learning_curve import LearningCurveTracker
    t = _learning_tracker()
    # Rank the few metrics we care most about. Missing ones just skip.
    out: list[dict[str, Any]] = []
    for metric in ("roas", "cvr", "acc", "f1"):
        curves = t.rank(metric, window=50, top_n=3)
        for c in curves:
            if c.trend != "insufficient":
                out.append(c.as_dict())
    return out


# ── v22 singletons ──────────────────────────────────────────

_CASE_BASE: Any = None
_CASE_LOCK = threading.Lock()


def _case_base():
    global _CASE_BASE
    if _CASE_BASE is None:
        with _CASE_LOCK:
            if _CASE_BASE is None:
                from core.memory.case_based_reasoner import CaseBasedReasoner
                _CASE_BASE = CaseBasedReasoner()
    return _CASE_BASE


def _case_base_summary() -> dict[str, Any]:
    return _case_base().stats()


_SKILL_LIB: Any = None
_SKILL_LOCK = threading.Lock()


def _skill_library():
    global _SKILL_LIB
    if _SKILL_LIB is None:
        with _SKILL_LOCK:
            if _SKILL_LIB is None:
                from core.brain.skill_library import SkillLibrary
                _SKILL_LIB = SkillLibrary()
    return _SKILL_LIB


def _skill_rank_summary() -> list[dict[str, Any]]:
    return [s.as_dict() for s in _skill_library().rank(min_support=3)][:5]


_COMPETENCE: Any = None
_COMPETENCE_LOCK = threading.Lock()


def _competence_model():
    global _COMPETENCE
    if _COMPETENCE is None:
        with _COMPETENCE_LOCK:
            if _COMPETENCE is None:
                from core.brain.competence_model import CompetenceModel
                _COMPETENCE = CompetenceModel()
    return _COMPETENCE


def _competence_summary() -> dict[str, Any]:
    return _competence_model().summary()


_CURIOSITY: Any = None
_CURIOSITY_LOCK = threading.Lock()


def _curiosity_engine():
    global _CURIOSITY
    if _CURIOSITY is None:
        with _CURIOSITY_LOCK:
            if _CURIOSITY is None:
                from core.brain.curiosity_engine import CuriosityEngine
                _CURIOSITY = CuriosityEngine()
    return _CURIOSITY


def _curiosity_summary() -> dict[str, Any]:
    return _curiosity_engine().stats()


_DRIFT: Any = None
_DRIFT_LOCK = threading.Lock()


def _drift_detector():
    global _DRIFT
    if _DRIFT is None:
        with _DRIFT_LOCK:
            if _DRIFT is None:
                from core.memory.concept_drift_detector import ConceptDriftDetector
                _DRIFT = ConceptDriftDetector()
    return _DRIFT


def _drift_summary() -> dict[str, Any]:
    return _drift_detector().summary()


# ── v23 singletons ──────────────────────────────────────────

_GOAL_GRAPH: Any = None
_GOAL_LOCK = threading.Lock()


def _goal_graph():
    global _GOAL_GRAPH
    if _GOAL_GRAPH is None:
        with _GOAL_LOCK:
            if _GOAL_GRAPH is None:
                from core.brain.goal_graph import GoalGraph
                _GOAL_GRAPH = GoalGraph()
    return _GOAL_GRAPH


def _goal_summary() -> dict[str, Any]:
    return _goal_graph().stats()


_ATTENTION: Any = None
_ATTENTION_LOCK = threading.Lock()


def _attention_filter():
    global _ATTENTION
    if _ATTENTION is None:
        with _ATTENTION_LOCK:
            if _ATTENTION is None:
                from core.brain.attention_filter import AttentionFilter
                _ATTENTION = AttentionFilter()
    return _ATTENTION


def _attention_summary() -> dict[str, Any]:
    return _attention_filter().stats()


# ── v25 singletons ──────────────────────────────────────────

_OWNER: Any = None
_OWNER_LOCK = threading.Lock()


def _owner_model():
    global _OWNER
    if _OWNER is None:
        with _OWNER_LOCK:
            if _OWNER is None:
                from core.brain.owner_model import OwnerModel
                _OWNER = OwnerModel()
    return _OWNER


def _owner_summary() -> dict[str, Any]:
    return _owner_model().summary()


_SAFETY_GUARD: Any = None
_SAFETY_LOCK = threading.Lock()


def _safety_guard():
    global _SAFETY_GUARD
    if _SAFETY_GUARD is None:
        with _SAFETY_LOCK:
            if _SAFETY_GUARD is None:
                from core.brain.action_safety_guard import (
                    ActionSafetyGuard,
                )
                _SAFETY_GUARD = ActionSafetyGuard()
    return _SAFETY_GUARD


_BUDGET_LEDGER: Any = None
_BUDGET_LOCK = threading.Lock()


def _budget_ledger():
    global _BUDGET_LEDGER
    if _BUDGET_LEDGER is None:
        with _BUDGET_LOCK:
            if _BUDGET_LEDGER is None:
                from core.brain.budget_ledger import BudgetLedger
                _BUDGET_LEDGER = BudgetLedger()
    return _BUDGET_LEDGER


def _budget_summary() -> list[dict[str, Any]]:
    return [s.as_dict() for s in _budget_ledger().overview()]


_EXPERIMENT_MANAGER: Any = None
_EXP_LOCK = threading.Lock()


def _experiment_manager():
    global _EXPERIMENT_MANAGER
    if _EXPERIMENT_MANAGER is None:
        with _EXP_LOCK:
            if _EXPERIMENT_MANAGER is None:
                from core.brain.experiment_manager import (
                    ExperimentManager,
                )
                _EXPERIMENT_MANAGER = ExperimentManager()
    return _EXPERIMENT_MANAGER


def _experiment_summary() -> dict[str, Any]:
    return _experiment_manager().stats()


_UPLIFT: Any = None
_UPLIFT_LOCK = threading.Lock()


def _uplift_estimator():
    global _UPLIFT
    if _UPLIFT is None:
        with _UPLIFT_LOCK:
            if _UPLIFT is None:
                from core.brain.uplift_estimator import UpliftEstimator
                _UPLIFT = UpliftEstimator()
    return _UPLIFT


def _uplift_summary() -> dict[str, Any]:
    return _uplift_estimator().stats()


_KNOWLEDGE_GRAPH: Any = None
_KG_LOCK = threading.Lock()


def _knowledge_graph():
    global _KNOWLEDGE_GRAPH
    if _KNOWLEDGE_GRAPH is None:
        with _KG_LOCK:
            if _KNOWLEDGE_GRAPH is None:
                from core.memory.knowledge_graph import KnowledgeGraph
                _KNOWLEDGE_GRAPH = KnowledgeGraph()
    return _KNOWLEDGE_GRAPH


def _knowledge_summary() -> dict[str, Any]:
    return _knowledge_graph().stats()


# ── Singleton ────────────────────────────────────────────────

_LOCK = threading.Lock()
_BRAIN: BrainFacade | None = None


def brain() -> BrainFacade:
    """Single entry point — ``brain().think(...)`` etc."""
    global _BRAIN
    if _BRAIN is None:
        with _LOCK:
            if _BRAIN is None:
                _BRAIN = BrainFacade()
    return _BRAIN
