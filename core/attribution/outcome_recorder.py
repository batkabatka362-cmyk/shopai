"""Outcome recorder — close the loop from Shopify outcome → brain.

Until this module existed, the learning loop was half-closed:
``OrderWebhookHandler`` routed paid orders to the legacy outcome /
kpi / revenue trackers, but none of the v33-v38 brain learners saw a
single real outcome. Calibration, prediction drift, capability
proficiency, funnel, and revenue-funnel all stayed blind to actual
revenue events.

``OutcomeRecorder`` is the single entry point. Given a normalised
outcome event it:

  • records a calibration sample on meta_reasoner if a decision_id
    + claimed_confidence are supplied
  • records a prediction on world_model_updater if a predictor_id
    + predicted value are supplied
  • updates capability_registry for the named capability
  • ingests a purchase / return into revenue_funnel
  • feeds the observed KPI into predictive_alerter + forecaster
  • advances mood_model (win / error)

Every method is wrapped in try/except and gated by
``SHOPAI_BRAIN_HOOKS=1``. Legacy trackers keep running in parallel
on the caller side; this module does not touch them.

Pure stdlib, deterministic. The single ``record`` method accepts a
``OutcomeEvent`` dataclass so callers build one struct and the
recorder fans it out to every brain learner.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("attribution.outcome_recorder")


@dataclass
class OutcomeEvent:
    """Normalised outcome ready to feed every brain learner.

    Fields that aren't applicable can be left empty / None; the
    recorder decides which learner to call based on what's present.
    """
    kind: str                       # "purchase" | "return" | "cancel"
    ok: bool
    revenue: float = 0.0
    cost: float = 0.0
    decision_id: str = ""
    claimed_confidence: float = 0.0  # 0..1 if known
    predictor_id: str = ""
    predicted_value: float | None = None
    observed_value: float | None = None
    capability_name: str = ""
    kpi: str = ""                    # e.g. "revenue" / "roas"
    kpi_value: float | None = None
    signals: tuple[str, ...] = ()    # for meta_reasoner.signal_use
    note: str = ""
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "revenue": round(self.revenue, 4),
            "cost": round(self.cost, 4),
            "decision_id": self.decision_id,
            "claimed_confidence": (
                round(self.claimed_confidence, 4)
                if self.claimed_confidence else 0.0
            ),
            "predictor_id": self.predictor_id,
            "predicted_value": self.predicted_value,
            "observed_value": self.observed_value,
            "capability_name": self.capability_name,
            "kpi": self.kpi,
            "kpi_value": self.kpi_value,
            "signals": list(self.signals),
            "note": self.note,
            "ts": self.ts,
        }


@dataclass
class RecordResult:
    event_id: str
    recorded: dict[str, bool]
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "recorded": dict(self.recorded),
            "note": self.note,
        }


def _hooks_enabled() -> bool:
    return os.getenv("SHOPAI_BRAIN_HOOKS", "") == "1"


def _moby_actual_from_event(event: "OutcomeEvent") -> str:
    """Map an OutcomeEvent into the action-token space Moby
    records in its disagreement log. Empty string means 'no
    actionable outcome to record'.

    Mapping rationale:
      * purchase + launched capability → ``activate``
        (the decision to turn the campaign on paid off)
      * return / cancel              → ``pause``
        (the campaign should have stayed off)
      * non-launch purchases are ignored here — they don't
        carry a campaign-level action signal.
    """
    if event.kind == "purchase" and event.capability_name in (
        "launch_sku",
    ):
        return "activate"
    if event.kind in ("return", "cancel"):
        return "pause"
    return ""


class OutcomeRecorder:
    """Feeds normalised outcome events into v33-v38 brain learners.

    Stateless thin shim — delegates to the brain_facade singletons.
    Safe to instantiate per-call.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recorded_count = 0

    def record(self, event: OutcomeEvent) -> RecordResult:
        if not event.kind:
            raise ValueError("event.kind required")
        if event.ts == 0.0:
            event.ts = time.time()
        # event_id used both as a trace handle and a dedupe hint
        import uuid
        event_id = (
            f"oe_{uuid.uuid4().hex[:10]}_{int(event.ts)}"
        )
        recorded: dict[str, bool] = {}
        note_bits: list[str] = []

        if not _hooks_enabled():
            return RecordResult(
                event_id=event_id,
                recorded={},
                note="brain hooks disabled",
            )

        # Lazy import — avoid forcing brain facade load when the
        # webhook path doesn't have hooks enabled.
        try:
            from core.brain.brain_facade import brain
            b = brain()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "brain facade unavailable: %s", exc,
            )
            return RecordResult(
                event_id=event_id,
                recorded={},
                note=f"brain unavailable: {exc}",
            )

        # 1. Calibration signal for the decision, if any
        if event.decision_id and event.claimed_confidence:
            try:
                b.record_calibration(
                    decision_id=event.decision_id,
                    claimed_confidence=float(
                        event.claimed_confidence,
                    ),
                    outcome_positive=bool(event.ok),
                )
                recorded["calibration"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "calibration record failed: %s", exc,
                )
                recorded["calibration"] = False
            # Signal-use record if caller supplied which signals
            # drove the decision
            if event.signals and event.decision_id:
                try:
                    b.record_signal_use(
                        decision_id=event.decision_id,
                        signals=list(event.signals),
                        outcome_positive=bool(event.ok),
                    )
                    recorded["signal_use"] = True
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "signal_use record failed: %s", exc,
                    )
                    recorded["signal_use"] = False

        # 2. World-model drift: (predicted, observed) pair
        if (
            event.predictor_id
            and event.predicted_value is not None
            and event.observed_value is not None
        ):
            try:
                b.record_prediction(
                    predictor_id=event.predictor_id,
                    predicted=float(event.predicted_value),
                    observed=float(event.observed_value),
                )
                recorded["prediction"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "prediction record failed: %s", exc,
                )
                recorded["prediction"] = False

        # 3. Capability proficiency
        if event.capability_name:
            try:
                b.update_capability(
                    event.capability_name, ok=bool(event.ok),
                )
                recorded["capability"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "capability update failed: %s", exc,
                )
                recorded["capability"] = False

        # 4. Funnel event
        stage = None
        if event.kind == "purchase":
            stage = "purchase"
        elif event.kind == "return":
            stage = "return"
        if stage is not None:
            try:
                b.record_funnel_event(stage, 1)
                recorded["funnel"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "funnel record failed: %s", exc,
                )
                recorded["funnel"] = False

        # 5. KPI trajectory
        if event.kpi and event.kpi_value is not None:
            try:
                b.observe_kpi(
                    event.kpi, float(event.kpi_value),
                )
                recorded["kpi"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "kpi observe failed: %s", exc,
                )
                recorded["kpi"] = False

        # 6. Mood tick — purchases are wins, returns/cancels are errors
        try:
            mood_event = (
                "win" if event.ok and event.kind == "purchase"
                else "error" if not event.ok
                else "flat"
            )
            b.observe_mood(mood_event)
            recorded["mood"] = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("mood observe failed: %s", exc)
            recorded["mood"] = False

        # 7. Moby vote-comparator resolve (Wave C-1 A7).
        #    When an outcome lands for a decision that had a
        #    pending moby/shopai vote disagreement, close it
        #    with the actual action taken so win-rate becomes
        #    a trust signal, not a guess.
        if event.decision_id and event.kind in (
            "purchase", "launch", "return", "cancel",
        ):
            try:
                from core.brain.moby_vote_comparator import (
                    get_moby_vote_comparator,
                )
                actual = _moby_actual_from_event(event)
                if actual:
                    get_moby_vote_comparator().resolve_outcome(
                        decision_id=event.decision_id,
                        actual=actual,
                    )
                    recorded["moby_resolved"] = True
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "moby resolve skipped: %s", exc,
                )

        with self._lock:
            self._recorded_count += 1
        return RecordResult(
            event_id=event_id,
            recorded=recorded,
            note="; ".join(note_bits),
        )

    def record_purchase(
        self,
        *,
        revenue: float,
        decision_id: str = "",
        claimed_confidence: float = 0.0,
        signals: tuple[str, ...] = (),
        capability_name: str = "",
    ) -> RecordResult:
        """Convenience for the common case."""
        return self.record(OutcomeEvent(
            kind="purchase",
            ok=True,
            revenue=float(revenue),
            decision_id=str(decision_id),
            claimed_confidence=float(claimed_confidence),
            signals=tuple(signals),
            capability_name=str(capability_name),
            kpi="revenue",
            kpi_value=float(revenue),
        ))

    def record_return(
        self,
        *,
        revenue: float,
        decision_id: str = "",
        claimed_confidence: float = 0.0,
    ) -> RecordResult:
        return self.record(OutcomeEvent(
            kind="return",
            ok=False,
            revenue=float(revenue),
            decision_id=str(decision_id),
            claimed_confidence=float(claimed_confidence),
            kpi="revenue",
            kpi_value=-float(revenue),   # signed: refund
        ))

    def record_cancel(
        self,
        *,
        decision_id: str = "",
        claimed_confidence: float = 0.0,
    ) -> RecordResult:
        return self.record(OutcomeEvent(
            kind="cancel",
            ok=False,
            decision_id=str(decision_id),
            claimed_confidence=float(claimed_confidence),
        ))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "recorded_count": self._recorded_count,
                "hooks_enabled": _hooks_enabled(),
            }

    def reset(self) -> int:
        with self._lock:
            n = self._recorded_count
            self._recorded_count = 0
        return n
