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
        return snap

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
