"""Outcome router — fan one outcome event to every interested module.

When an order arrives or a hypothesis resolves, *eight* different
subsystems should learn from it:

  • reward_model    — fold (features, sign) into preference LLRs
  • trust_calibrator — update (source, correct) for the origin
  • epistemic       — observe the feature cell
  • habit           — record (signature, action, success)
  • world_model     — fold (context, action, kpi, value)
  • hypothesis      — resolve the prediction tied to the decision
  • policy_library  — record_outcome for the matched policy
  • memory          — persist the event itself

Today each call site plumbs whichever subset it remembered,
which means coverage is always lower than it should be.

OutcomeRouter is a pub/sub dispatcher keyed by event kind. The
caller emits one structured Outcome; every subscriber receives
it and updates its own state. Failures in one subscriber are
isolated — the others still fire. Errors are logged for later
inspection.

Default subscribers ship with sensible mappings for the
``order``, ``hypothesis_resolved``, and ``decision_feedback`` event
kinds. Additional kinds + handlers can be registered with
``subscribe(kind, handler)``.

Pure orchestrator; every subscriber is optional (skipped if its
target module is unavailable).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from utils.logger import get_logger


logger = get_logger("brain.outcome_router")


@dataclass
class Outcome:
    kind: str                         # order / hypothesis_resolved / ...
    features: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    sign: float = 0.0                 # −1..+1 polarity
    success: bool = True
    value: float | None = None        # observed KPI numeric
    kpi: str | None = None
    action: str | None = None
    hypothesis_id: str | None = None
    policy_name: str | None = None
    habit_signature: str | None = None
    memory_fields: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "features": self.features,
            "source": self.source,
            "sign": self.sign,
            "success": self.success,
            "value": self.value,
            "kpi": self.kpi,
            "action": self.action,
            "hypothesis_id": self.hypothesis_id,
            "policy_name": self.policy_name,
            "habit_signature": self.habit_signature,
            "memory_fields": self.memory_fields,
        }


@dataclass
class DispatchReport:
    delivered: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivered": self.delivered,
            "skipped": self.skipped,
            "errors": self.errors,
        }


Handler = Callable[[Outcome], None]


# ── Router ─────────────────────────────────────────────────

class OutcomeRouter:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[str, Handler]]] = {}
        self._lock = threading.Lock()
        self._install_defaults()

    # ── Subscription ───────────────────────────────────────

    def subscribe(
        self, kind: str, handler: Handler, name: str = "",
    ) -> None:
        with self._lock:
            self._subscribers.setdefault(kind, []).append(
                (name or handler.__name__, handler),
            )

    def unsubscribe(self, kind: str, name: str) -> bool:
        with self._lock:
            subs = self._subscribers.get(kind, [])
            new_subs = [(n, h) for n, h in subs if n != name]
            if len(new_subs) == len(subs):
                return False
            self._subscribers[kind] = new_subs
            return True

    def clear(self, kind: str | None = None) -> None:
        with self._lock:
            if kind is None:
                self._subscribers.clear()
            else:
                self._subscribers.pop(kind, None)

    def subscribers(self, kind: str) -> list[str]:
        with self._lock:
            return [n for n, _ in self._subscribers.get(kind, [])]

    # ── Emit ───────────────────────────────────────────────

    def emit(self, outcome: Outcome) -> DispatchReport:
        report = DispatchReport()
        with self._lock:
            subs = list(self._subscribers.get(outcome.kind, []))
        if not subs:
            report.skipped.append(f"no subscribers for {outcome.kind}")
            return report
        for name, handler in subs:
            try:
                handler(outcome)
                report.delivered.append(name)
            except Exception as exc:
                logger.warning(
                    "outcome subscriber %s raised: %s", name, exc,
                )
                report.errors.append((name, f"{type(exc).__name__}: {exc}"))
        return report

    # ── Default fan-out ────────────────────────────────────

    def _install_defaults(self) -> None:
        # Order outcomes: feed every downstream learner that can learn
        # from a confirmed customer action.
        self.subscribe("order", _handle_reward, "reward_model")
        self.subscribe("order", _handle_trust, "trust_calibrator")
        self.subscribe("order", _handle_epistemic, "epistemic")
        self.subscribe("order", _handle_habit, "habit")
        self.subscribe("order", _handle_world_model, "world_model")
        self.subscribe("order", _handle_policy_outcome, "policy_library")

        # Hypothesis resolution: resolve + reward + trust
        self.subscribe(
            "hypothesis_resolved", _handle_hypothesis_resolve,
            "hypothesis",
        )
        self.subscribe(
            "hypothesis_resolved", _handle_reward, "reward_model",
        )
        self.subscribe(
            "hypothesis_resolved", _handle_policy_outcome,
            "policy_library",
        )

        # Generic decision feedback: reward + habit + policy
        self.subscribe(
            "decision_feedback", _handle_reward, "reward_model",
        )
        self.subscribe(
            "decision_feedback", _handle_habit, "habit",
        )
        self.subscribe(
            "decision_feedback", _handle_policy_outcome,
            "policy_library",
        )


# ── Individual handlers (lazy imports) ──────────────────────

def _handle_reward(outcome: Outcome) -> None:
    if not outcome.features or outcome.sign == 0:
        return
    try:
        from core.brain.reward_model import reward_model
        reward_model().record(outcome.features, outcome.sign)
    except Exception as exc:
        logger.debug("reward handler: %s", exc)


def _handle_trust(outcome: Outcome) -> None:
    if not outcome.source:
        return
    try:
        from core.brain.trust_calibrator import TrustCalibrator
        TrustCalibrator().update(outcome.source, outcome.success)
    except Exception as exc:
        logger.debug("trust handler: %s", exc)


def _handle_epistemic(outcome: Outcome) -> None:
    if not outcome.features:
        return
    try:
        from core.brain.epistemic import coverage_engine
        coverage_engine().observe(outcome.features)
    except Exception as exc:
        logger.debug("epistemic handler: %s", exc)


def _handle_habit(outcome: Outcome) -> None:
    if not outcome.habit_signature or not outcome.action:
        return
    try:
        from core.brain.habit import HabitLayer
        HabitLayer().observe(
            outcome.habit_signature,
            outcome.action,
            success=outcome.success,
        )
    except Exception as exc:
        logger.debug("habit handler: %s", exc)


def _handle_world_model(outcome: Outcome) -> None:
    if not outcome.action or not outcome.kpi or outcome.value is None:
        return
    try:
        from core.brain.world_model import (
            Context, world_model, ACTIONS, KPIS,
        )
        if outcome.action not in ACTIONS or outcome.kpi not in KPIS:
            return
        ctx = Context(
            niche=outcome.features.get("niche", "unknown"),
            price_band=outcome.features.get("price_band", "mid"),
            margin_band=outcome.features.get("margin_band", "mid"),
            copy_tone=outcome.features.get("copy_tone", "friendly"),
        )
        world_model().update(
            ctx, str(outcome.action), str(outcome.kpi),
            float(outcome.value),
        )
    except Exception as exc:
        logger.debug("world_model handler: %s", exc)


def _handle_hypothesis_resolve(outcome: Outcome) -> None:
    if not outcome.hypothesis_id or outcome.value is None:
        return
    try:
        from core.brain.hypothesis import engine
        engine().resolve(
            outcome.hypothesis_id,
            observed=float(outcome.value),
        )
    except Exception as exc:
        logger.debug("hypothesis resolve handler: %s", exc)


def _handle_policy_outcome(outcome: Outcome) -> None:
    if not outcome.policy_name:
        return
    try:
        from core.brain.policy_library import PolicyLibrary
        PolicyLibrary().record_outcome(
            outcome.policy_name, outcome.success,
        )
    except Exception as exc:
        logger.debug("policy handler: %s", exc)


# ── Singleton ────────────────────────────────────────────────

_ROUTER_LOCK = threading.Lock()
_ROUTER: OutcomeRouter | None = None


def router() -> OutcomeRouter:
    global _ROUTER
    if _ROUTER is None:
        with _ROUTER_LOCK:
            if _ROUTER is None:
                _ROUTER = OutcomeRouter()
    return _ROUTER
