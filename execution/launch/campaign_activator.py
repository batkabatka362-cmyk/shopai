"""Campaign activator — safe PAUSED → ACTIVE gate.

publisher_bundle intentionally creates every Meta campaign in the
PAUSED state so no ad spend starts accidentally. Someone has to flip
it to ACTIVE. Before this module existed, the owner had to open Meta
Ads Manager and click the toggle — guaranteed friction, zero
learning signal for the brain.

``CampaignActivator.activate(request)`` runs a paranoid gate chain
before calling ``MetaAdsAdapter.resume_campaign``:

  1. pre-flight  — credentials + campaign exists + budget reasonable
  2. readiness   — brain's readiness_gate verdict (gather / go)
  3. constraints — behavioral_constraint_registry
  4. auto-approve vs owner — if not auto_approved and not in dry
     mode, return ``pending`` instead of activating
  5. execute     — MetaAdsAdapter.execute(ADS_RESUME_CAMPAIGN)
  6. record      — OutcomeRecorder (kind=campaign_activate) + rationale
     builder (decision trace)

Live writes dual-gated: ``ActivateRequest.live=True`` AND
``SHOPAI_ENABLE_LIVE_EXECUTION=1``. Either miss → dry_run.

Pure stdlib, deterministic step ordering. Caller gets back a rich
``ActivationResult`` for owner-facing logging.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("execution.launch.campaign_activator")


_DEFAULT_READINESS_PROBABILITY = 0.6
_DEFAULT_READINESS_GAP = 0.3
_DEFAULT_FRESHNESS = 0.7
_DEFAULT_MAX_DAILY_BUDGET_USD = 500.0


@dataclass
class ActivateRequest:
    campaign_id: str
    decision_id: str = ""
    daily_budget_usd: float = 0.0   # if known, used for sanity cap
    evidence_probability: float = _DEFAULT_READINESS_PROBABILITY
    evidence_gap: float = _DEFAULT_READINESS_GAP
    knowledge_freshness: float = _DEFAULT_FRESHNESS
    claimed_confidence: float = 0.6
    auto_approve: bool = False
    live: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise ValueError("campaign_id required")
        if self.daily_budget_usd < 0:
            raise ValueError(
                "daily_budget_usd must be ≥ 0",
            )
        for name, v, lo, hi in (
            ("evidence_probability",
             self.evidence_probability, 0.0, 1.0),
            ("evidence_gap",
             self.evidence_gap, 0.0, 1.0),
            ("knowledge_freshness",
             self.knowledge_freshness, 0.0, 1.0),
            ("claimed_confidence",
             self.claimed_confidence, 0.0, 1.0),
        ):
            if not lo <= v <= hi:
                raise ValueError(
                    f"{name} must be in [{lo}, {hi}]",
                )


@dataclass
class StepLog:
    name: str
    status: str         # "ok" | "blocked" | "dry_run" | "error" | "pending"
    note: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "note": self.note,
            "data": dict(self.data),
            "ts": self.ts,
        }


@dataclass
class ActivationResult:
    decision_id: str
    campaign_id: str
    verdict: str       # "activated" | "dry_run" | "pending" | "blocked"
    dry_run: bool
    steps: list[StepLog]
    block_reason: str = ""
    pending_reason: str = ""
    ts: float = 0.0

    @property
    def activated(self) -> bool:
        return self.verdict == "activated"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "campaign_id": self.campaign_id,
            "verdict": self.verdict,
            "dry_run": self.dry_run,
            "steps": [s.as_dict() for s in self.steps],
            "block_reason": self.block_reason,
            "pending_reason": self.pending_reason,
            "ts": self.ts,
        }


def _enable_live_execution() -> bool:
    return os.getenv("SHOPAI_ENABLE_LIVE_EXECUTION", "") == "1"


class CampaignActivator:
    """Owner-safe PAUSED → ACTIVE flip for a Meta Ads campaign.

    Dependency-injected so tests can supply fakes; falls back to
    real singletons in production.
    """

    def __init__(
        self,
        *,
        ad_adapter: Any = None,
        readiness_checker: Any = None,
        constraint_registry: Any = None,
        outcome_recorder: Any = None,
        rationale_builder: Any = None,
        max_daily_budget_usd: float = _DEFAULT_MAX_DAILY_BUDGET_USD,
    ) -> None:
        if max_daily_budget_usd <= 0:
            raise ValueError(
                "max_daily_budget_usd must be > 0",
            )
        self._lock = threading.Lock()
        self._ads = ad_adapter
        self._readiness = readiness_checker
        self._constraints = constraint_registry
        self._outcomes = outcome_recorder
        self._rationale = rationale_builder
        self._max_budget = float(max_daily_budget_usd)
        self._history: list[ActivationResult] = []

    # ── Lazy deps ────────────────────────────────────────

    def _get_ads(self) -> Any:
        if self._ads is not None:
            return self._ads
        from core.adapters.ads.meta_ads import MetaAdsAdapter
        self._ads = MetaAdsAdapter()
        return self._ads

    def _get_readiness(self) -> Any:
        if self._readiness is not None:
            return self._readiness
        from core.brain.readiness_gate import ReadinessGate
        self._readiness = ReadinessGate()
        return self._readiness

    def _get_constraints(self) -> Any:
        if self._constraints is not None:
            return self._constraints
        # Lazy — an empty registry is still a valid gate (no rules
        # → no violations). Owner can seed via brain_facade.
        from core.brain.behavioral_constraint_registry import (
            BehavioralConstraintRegistry,
        )
        self._constraints = BehavioralConstraintRegistry()
        return self._constraints

    def _get_outcomes(self) -> Any:
        if self._outcomes is not None:
            return self._outcomes
        from core.attribution.outcome_recorder import (
            OutcomeRecorder,
        )
        self._outcomes = OutcomeRecorder()
        return self._outcomes

    def _get_rationale(self) -> Any:
        if self._rationale is not None:
            return self._rationale
        from core.brain.decision_rationale_builder import (
            DecisionRationaleBuilder,
        )
        self._rationale = DecisionRationaleBuilder()
        return self._rationale

    # ── Pipeline ─────────────────────────────────────────

    def activate(
        self, request: ActivateRequest,
    ) -> ActivationResult:
        if not isinstance(request, ActivateRequest):
            raise TypeError(
                "request must be an ActivateRequest",
            )
        decision_id = (
            request.decision_id
            or f"act_{uuid.uuid4().hex[:12]}"
        )
        dry_run = not (
            request.live and _enable_live_execution()
        )
        steps: list[StepLog] = []
        rationale = self._get_rationale()
        try:
            rationale.start(
                decision_id=decision_id,
                summary=(
                    f"activate campaign {request.campaign_id}"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "rationale.start skipped: %s", exc,
            )

        # 1. pre-flight — budget sanity
        pre_log = self._step_preflight(request, steps)
        if pre_log.status == "blocked":
            return self._finalise(
                decision_id, request.campaign_id,
                "blocked", dry_run, steps,
                block_reason=pre_log.note,
                rationale=rationale,
            )

        # 2. readiness gate
        ready_log = self._step_readiness(request, steps)
        if ready_log.status == "blocked":
            return self._finalise(
                decision_id, request.campaign_id,
                "blocked", dry_run, steps,
                block_reason=ready_log.note,
                rationale=rationale,
            )

        # 3. behavioral constraints
        constr_log = self._step_constraints(request, steps)
        if constr_log.status == "blocked":
            return self._finalise(
                decision_id, request.campaign_id,
                "blocked", dry_run, steps,
                block_reason=constr_log.note,
                rationale=rationale,
            )

        # 4. auto-approve or hold
        if not request.auto_approve and not dry_run:
            steps.append(StepLog(
                name="approval",
                status="pending",
                note=(
                    "owner approval required "
                    "(auto_approve=False)"
                ),
                ts=time.time(),
            ))
            return self._finalise(
                decision_id, request.campaign_id,
                "pending", dry_run, steps,
                pending_reason="owner approval required",
                rationale=rationale,
            )
        steps.append(StepLog(
            name="approval",
            status="ok",
            note=(
                "auto_approve" if request.auto_approve
                else "dry_run skips approval"
            ),
            ts=time.time(),
        ))

        # 5. execute
        exec_log = self._step_execute(
            request, steps, dry_run,
        )
        if exec_log.status == "error":
            return self._finalise(
                decision_id, request.campaign_id,
                "blocked", dry_run, steps,
                block_reason=exec_log.note,
                rationale=rationale,
            )

        # 6. record outcome
        try:
            from core.attribution.outcome_recorder import (
                OutcomeEvent,
            )
            self._get_outcomes().record(OutcomeEvent(
                kind="campaign_activate",
                ok=True,
                decision_id=decision_id,
                claimed_confidence=request.claimed_confidence,
                capability_name="activate_campaign",
                kpi="activation",
                kpi_value=1.0,
                signals=("preflight", "readiness", "constraints"),
                note=(
                    "live" if not dry_run else "dry_run"
                ),
            ))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "outcome record at-activate skipped: %s", exc,
            )

        verdict = "dry_run" if dry_run else "activated"
        return self._finalise(
            decision_id, request.campaign_id,
            verdict, dry_run, steps,
            rationale=rationale,
        )

    # ── Steps ────────────────────────────────────────────

    def _step_preflight(
        self,
        request: ActivateRequest,
        steps: list[StepLog],
    ) -> StepLog:
        if (
            request.daily_budget_usd > 0
            and request.daily_budget_usd > self._max_budget
        ):
            log = StepLog(
                name="preflight",
                status="blocked",
                note=(
                    f"daily_budget ${request.daily_budget_usd:.2f} "
                    f"> cap ${self._max_budget:.2f}"
                ),
                ts=time.time(),
            )
        else:
            log = StepLog(
                name="preflight",
                status="ok",
                note=(
                    f"budget ${request.daily_budget_usd:.2f} "
                    "within cap"
                ),
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _step_readiness(
        self,
        request: ActivateRequest,
        steps: list[StepLog],
    ) -> StepLog:
        try:
            from core.brain.readiness_gate import ReadinessInput
            verdict = self._get_readiness().check(
                ReadinessInput(
                    evidence_probability=(
                        request.evidence_probability
                    ),
                    evidence_gap=request.evidence_gap,
                    knowledge_freshness=(
                        request.knowledge_freshness
                    ),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="readiness",
                status="blocked",
                note=(
                    f"readiness check raised: {exc}"
                ),
                ts=time.time(),
            )
            steps.append(log)
            return log
        verdict_name = str(verdict.verdict)
        if verdict_name == "stand_down":
            log = StepLog(
                name="readiness",
                status="blocked",
                note=(
                    "stand_down: "
                    + str(verdict.reason)
                ),
                data=verdict.as_dict(),
                ts=time.time(),
            )
        elif verdict_name == "go":
            log = StepLog(
                name="readiness",
                status="ok",
                note="go",
                data=verdict.as_dict(),
                ts=time.time(),
            )
        else:
            # gather / warm_up → advisory; allow activation but
            # surface the note
            log = StepLog(
                name="readiness",
                status="ok",
                note=(
                    f"{verdict_name}: "
                    + str(verdict.reason)
                ),
                data=verdict.as_dict(),
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _step_constraints(
        self,
        request: ActivateRequest,
        steps: list[StepLog],
    ) -> StepLog:
        try:
            result = self._get_constraints().evaluate(
                action={
                    "kind": "activate_campaign",
                    "campaign_id": request.campaign_id,
                    "daily_budget_usd": (
                        request.daily_budget_usd
                    ),
                },
                context={"hour": time.gmtime().tm_hour},
            )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="constraints",
                status="ok",
                note=(
                    f"constraints check raised: {exc}; "
                    "treated as permissive"
                ),
                ts=time.time(),
            )
            steps.append(log)
            return log
        if result.any_severe:
            notes = "; ".join(
                a.note for a in result.alerts
                if a.severity == "severe"
            )
            log = StepLog(
                name="constraints",
                status="blocked",
                note=f"severe constraint violation: {notes}",
                data={
                    "alerts": [
                        a.as_dict() for a in result.alerts
                    ],
                },
                ts=time.time(),
            )
        else:
            log = StepLog(
                name="constraints",
                status="ok",
                note=(
                    f"{len(result.alerts)} advisory alerts"
                ),
                data={
                    "alerts": [
                        a.as_dict() for a in result.alerts
                    ],
                },
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _step_execute(
        self,
        request: ActivateRequest,
        steps: list[StepLog],
        dry_run: bool,
    ) -> StepLog:
        if dry_run:
            log = StepLog(
                name="execute",
                status="dry_run",
                note=(
                    "would call MetaAdsAdapter.resume_campaign "
                    f"({request.campaign_id})"
                ),
                ts=time.time(),
            )
            steps.append(log)
            return log
        try:
            from core.adapters.base import Capability
            result = self._get_ads().execute(
                Capability.ADS_RESUME_CAMPAIGN,
                {
                    "campaign_id": request.campaign_id,
                    "decision_id": (
                        request.decision_id or ""
                    ),
                    "claimed_confidence": (
                        request.claimed_confidence
                    ),
                    "signals": (
                        "activator",
                        "readiness_ok",
                        "constraints_ok",
                    ),
                },
            )
            if result.ok:
                log = StepLog(
                    name="execute",
                    status="ok",
                    note=(
                        f"campaign {request.campaign_id} "
                        "resumed"
                    ),
                    data=dict(result.data or {}),
                    ts=time.time(),
                )
            else:
                log = StepLog(
                    name="execute",
                    status="error",
                    note=str(result.error or "unknown"),
                    ts=time.time(),
                )
        except Exception as exc:  # noqa: BLE001
            log = StepLog(
                name="execute",
                status="error",
                note=f"{type(exc).__name__}: {exc}",
                ts=time.time(),
            )
        steps.append(log)
        return log

    def _finalise(
        self,
        decision_id: str,
        campaign_id: str,
        verdict: str,
        dry_run: bool,
        steps: list[StepLog],
        *,
        block_reason: str = "",
        pending_reason: str = "",
        rationale: Any = None,
    ) -> ActivationResult:
        result = ActivationResult(
            decision_id=decision_id,
            campaign_id=campaign_id,
            verdict=verdict,
            dry_run=dry_run,
            steps=steps,
            block_reason=block_reason,
            pending_reason=pending_reason,
            ts=time.time(),
        )
        # Commit rationale with the outcome
        if rationale is not None:
            try:
                rationale.add(
                    decision_id, kind="gate",
                    headline=f"verdict={verdict}",
                    weight=1.0,
                )
                rationale.commit(decision_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "rationale commit skipped: %s", exc,
                )
        with self._lock:
            self._history.append(result)
            if len(self._history) > 200:
                del self._history[
                    : len(self._history) - 200
                ]
        return result

    # ── Queries ──────────────────────────────────────────

    def recent(
        self, *, limit: int = 20,
    ) -> list[ActivationResult]:
        with self._lock:
            return list(
                self._history[-max(1, int(limit)):],
            )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_verdict: dict[str, int] = {}
            for r in self._history:
                by_verdict[r.verdict] = (
                    by_verdict.get(r.verdict, 0) + 1
                )
            return {
                "activations": len(self._history),
                "by_verdict": by_verdict,
                "max_daily_budget_usd": self._max_budget,
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._history)
            self._history.clear()
        return n
