"""Engine outcome bus — fan out a single event to every sink.

Shopai has ~2,500 engines. Wiring each one to every hardening
track (RuleBook, WorldModelCalibration, SourceTrustCalibrator,
FreshnessTracker, PatternMiner, RationaleLedger) would be 15k+
call sites and a support nightmare. This module is the single
wire every engine touches:

    bus.report(EngineOutcome(
        engine="pricing_engine",
        kpi="margin",
        value=0.22,
        ok=True,
        source="cj_dropshipping",
        context={"niche": "pet"},
        rationale_id="dec_abc123",
    ))

…and the bus fans out to:

  * RuleBook via PatternMiner (3+ similar outcomes → proposal)
  * WorldModelCalibration (predicted vs actual when predicted
    is supplied)
  * SourceTrustCalibrator (when source is set → record_outcome)
  * FreshnessTracker (every event → touch engine + source rows)
  * rationale_ledger (no-op here — caller persists Rationale
    separately; bus only references the id for cross-link)

Design:

  * Every sink is injectable for offline tests.
  * Every fan-out is wrapped in try/except so one broken sink
    never blocks the others.
  * Deterministic — a fixed sequence of reports produces a
    fixed set of sink calls.
  * Bounded: the PatternMiner fan-out runs on a sliding buffer
    of the last ``pattern_window`` events (default 200) so a
    long-running daemon doesn't accumulate unbounded state.

Pure stdlib. Thread-safe (RLock). LLM-free.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("core.integration.engine_outcome_bus")


_DEFAULT_PATTERN_WINDOW = 200
_DEFAULT_MINE_EVERY = 20


@dataclass
class EngineOutcome:
    engine: str
    kpi: str
    value: float
    ok: bool
    source: str = ""
    context: dict[str, Any] = field(
        default_factory=dict,
    )
    rationale_id: str = ""
    predicted: float | None = None
    ts: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "kpi": self.kpi,
            "value": self.value,
            "ok": self.ok,
            "source": self.source,
            "context": dict(self.context),
            "rationale_id": self.rationale_id,
            "predicted": self.predicted,
            "ts": self.ts,
        }


@dataclass
class BusReport:
    event_count: int
    sinks_invoked: tuple[str, ...] = ()
    sink_errors: dict[str, str] = field(
        default_factory=dict,
    )
    pattern_miner_ran: bool = False
    pattern_proposals: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "sinks_invoked": list(self.sinks_invoked),
            "sink_errors": dict(self.sink_errors),
            "pattern_miner_ran": self.pattern_miner_ran,
            "pattern_proposals": self.pattern_proposals,
        }


class EngineOutcomeBus:
    """Central fan-out for engine outcome events."""

    def __init__(
        self,
        *,
        rulebook: Any = None,
        pattern_miner: Any = None,
        world_calibration: Any = None,
        trust_calibrator: Any = None,
        freshness_tracker: Any = None,
        feedback_store: Any = None,
        mine_every: int = _DEFAULT_MINE_EVERY,
        pattern_window: int = _DEFAULT_PATTERN_WINDOW,
        now_fn: Any = None,
    ) -> None:
        if mine_every < 1:
            raise ValueError("mine_every must be ≥ 1")
        if pattern_window < mine_every:
            raise ValueError(
                "pattern_window must be ≥ mine_every",
            )
        self._lock = threading.RLock()
        self._rulebook = rulebook
        self._miner = pattern_miner
        self._world_calib = world_calibration
        self._trust = trust_calibrator
        self._freshness = freshness_tracker
        self._feedback = feedback_store
        self._mine_every = int(mine_every)
        self._buf: deque[EngineOutcome] = deque(
            maxlen=int(pattern_window),
        )
        self._total_reported = 0
        self._now_fn = now_fn or time.time
        # Sinks that never crash a single report
        self._sinks: list[tuple[
            str, Any,
        ]] = []

    # ── Lazy sinks ───────────────────────────────────────

    def _get_miner(self) -> Any:
        if self._miner is None:
            try:
                from core.learning.pattern_miner import (
                    PatternMiner,
                )
                self._miner = PatternMiner(
                    rulebook=self._rulebook,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "pattern_miner lazy load: %s", exc,
                )
        return self._miner

    def _get_world_calib(self) -> Any:
        if self._world_calib is None:
            try:
                from core.brain.world_model_calibration import (
                    get_world_model_calibration,
                )
                self._world_calib = (
                    get_world_model_calibration()
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "world_calib lazy load: %s", exc,
                )
        return self._world_calib

    def _get_trust(self) -> Any:
        if self._trust is None:
            try:
                from core.data.source_trust_calibrator import (
                    get_calibrator,
                )
                self._trust = get_calibrator()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "trust lazy load: %s", exc,
                )
        return self._trust

    def _get_freshness(self) -> Any:
        if self._freshness is None:
            try:
                from core.memory.freshness_tracker import (
                    get_freshness_tracker,
                )
                self._freshness = (
                    get_freshness_tracker()
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "freshness lazy load: %s", exc,
                )
        return self._freshness

    def _get_feedback(self) -> Any:
        if self._feedback is None:
            try:
                from core.learning.feedback_store import (
                    get_feedback_store,
                )
                self._feedback = get_feedback_store()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "feedback_store lazy load: %s", exc,
                )
        return self._feedback

    # ── Report ────────────────────────────────────────────

    def report(self, outcome: EngineOutcome) -> BusReport:
        if not isinstance(outcome, EngineOutcome):
            raise TypeError(
                "outcome must be EngineOutcome",
            )
        if not outcome.engine or not outcome.kpi:
            raise ValueError(
                "engine + kpi required",
            )
        if outcome.ts <= 0:
            outcome.ts = float(self._now_fn())
        errors: dict[str, str] = {}
        invoked: list[str] = []
        # Buffer for pattern miner
        with self._lock:
            self._buf.append(outcome)
            self._total_reported += 1
            buf_snapshot = list(self._buf)
            total = self._total_reported
        # World model calibration (only if predicted supplied)
        if outcome.predicted is not None:
            calib = self._get_world_calib()
            if calib is not None:
                try:
                    calib.record_outcome(
                        outcome.kpi,
                        predicted=float(
                            outcome.predicted,
                        ),
                        actual=float(outcome.value),
                    )
                    invoked.append("world_calibration")
                except Exception as exc:  # noqa: BLE001
                    errors["world_calibration"] = str(exc)
        # Source trust
        if outcome.source:
            trust = self._get_trust()
            if trust is not None:
                try:
                    trust.record_outcome(
                        outcome.source,
                        won=bool(outcome.ok),
                    )
                    invoked.append("source_trust")
                except Exception as exc:  # noqa: BLE001
                    errors["source_trust"] = str(exc)
        # Freshness — touch engine + source rows
        fresh = self._get_freshness()
        if fresh is not None:
            try:
                fresh.touch("engine", outcome.engine)
                if outcome.source:
                    fresh.touch(
                        "source", outcome.source,
                    )
                invoked.append("freshness")
            except Exception as exc:  # noqa: BLE001
                errors["freshness"] = str(exc)
        # Feedback store — per-engine ledger of ok/fail,
        # elapsed, and KPI snapshot. Rescues the previously
        # orphaned core.learning.feedback_store module (audit
        # batch 3 wire-up): every activator / publisher outcome
        # now shows up in `feedback_store.get_all_stats()`.
        fb = self._get_feedback()
        if fb is not None:
            try:
                fb.record(
                    engine_name=outcome.engine,
                    task_id=outcome.rationale_id or "",
                    status=(
                        "completed" if outcome.ok else "failed"
                    ),
                    elapsed_seconds=0.0,
                    input_summary=dict(outcome.context or {}),
                    output_summary={
                        "kpi": outcome.kpi,
                        "kpi_value": outcome.value,
                    },
                    quality_score=(
                        float(outcome.value)
                        if isinstance(
                            outcome.value, (int, float),
                        ) else None
                    ),
                )
                invoked.append("feedback_store")
            except Exception as exc:  # noqa: BLE001
                errors["feedback_store"] = str(exc)
        # Pattern miner (every `mine_every` reports)
        mined = False
        proposals = 0
        if total % self._mine_every == 0:
            miner = self._get_miner()
            if miner is not None:
                try:
                    report = miner.mine(
                        [
                            {
                                "capability_name": e.engine,
                                "kpi": e.kpi,
                                "kpi_value": e.value,
                                "ok": e.ok,
                            }
                            for e in buf_snapshot
                        ],
                    )
                    mined = True
                    proposals = int(
                        getattr(
                            report,
                            "proposals_emitted",
                            0,
                        ),
                    )
                    if mined:
                        invoked.append("pattern_miner")
                except Exception as exc:  # noqa: BLE001
                    errors["pattern_miner"] = str(exc)
        return BusReport(
            event_count=total,
            sinks_invoked=tuple(invoked),
            sink_errors=errors,
            pattern_miner_ran=mined,
            pattern_proposals=proposals,
        )

    # ── Introspection ────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_reported": self._total_reported,
                "buffer_size": len(self._buf),
                "mine_every": self._mine_every,
                "pattern_window": self._buf.maxlen,
            }

    def recent(
        self, *, limit: int = 20,
    ) -> list[EngineOutcome]:
        with self._lock:
            return list(self._buf)[
                -int(max(1, limit)):
            ]


# ── Singleton ───────────────────────────────────────────────

_SINGLETON: EngineOutcomeBus | None = None
_SINGLETON_LOCK = threading.Lock()


def get_engine_outcome_bus() -> EngineOutcomeBus:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = EngineOutcomeBus()
    return _SINGLETON


def reset_engine_outcome_bus_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
