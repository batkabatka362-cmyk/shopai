"""Per-engine health scorer.

Composes the signals scattered across the approval / quarantine /
alert-history / outcome stores into ONE engine-level health
score so operators (and CI / dashboards) can answer one
question -- "is this engine OK right now?" -- without
cross-referencing five CLI commands.

Inputs
------
For an engine name, the scorer pulls (best-effort, all
source-failure isolated):

  * ``stats_by_engine()`` -- count by status (pending / executed
    / failed).
  * ``engine_outcome_stats()`` -- positive/negative/neutral
    outcome counters + score (0..1).
  * ``quarantine.load_state()`` -- exempt / released /
    alert_paused flags.
  * ``alert_history.recent_history()`` + ``consecutive_runs_per_engine()``
    -- 7-day alert streak + last firing.

Output
------
:class:`EngineHealth` carries:

  * ``score`` -- integer 1..10 (10 = healthiest).
  * ``verdict`` -- ``"healthy"`` / ``"warning"`` / ``"unhealthy"``.
  * ``signals`` -- the raw rollup dict so downstream surfaces can
    inspect individual numbers without re-pulling.
  * ``concerns`` -- list of short human-readable strings ("alert
    streak 3 days", "outcome_score 35%") that drove a non-
    healthy verdict.

Scoring
-------
Deliberately simple and deterministic so an operator can audit
why a number is what it is:

  * Start at 10.
  * Subtract 4 if alert_paused (fleet or any per-store entry).
  * Subtract 2 per consecutive day in the alert streak (max 4).
  * Subtract 2 if outcome_score < 0.4 with >=5 polarised
    outcomes.
  * Subtract 1 if recent failure-rate (failed / (executed +
    failed)) >= 0.30 with >=5 recent executions.
  * Subtract 1 if quarantine "released" flag is set (operator
    cleared a prior quarantine -- engine should be monitored).
  * Add 1 if outcome_score >= 0.7 with >=5 polarised outcomes.
  * Clamp to [1, 10].

Verdict thresholds:
  * score >= 8: healthy.
  * 5 <= score < 8: warning.
  * score < 5: unhealthy.

CLI consumer: ``shopai engine pulse <engine>`` -- short,
opinionated, cron-friendly.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineHealth:
    engine: str
    score: int
    verdict: str
    signals: dict[str, Any] = field(default_factory=dict)
    concerns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "score": self.score,
            "verdict": self.verdict,
            "signals": dict(self.signals),
            "concerns": list(self.concerns),
        }


def score_engine(
    engine: str,
    *,
    queue: Any | None = None,
    now: float | None = None,
) -> EngineHealth:
    """Compute the engine's current health score.

    Args:
        engine: Engine name to score.
        queue: ApprovalQueue (or compatible). Defaults to the
            process singleton when omitted.
        now: Override timestamp; tests use this to fake the
            7-day window. Defaults to ``time.time()``.

    Returns:
        :class:`EngineHealth` -- never raises. Every signal
        collection is wrapped so a missing source degrades to
        ``signals[<name>] = None`` and the score reflects the
        signals that DID resolve.
    """
    if now is None:
        now = time.time()

    if queue is None:
        try:
            from core.approval.queue import get_approval_queue
            queue = get_approval_queue()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine_health: get_approval_queue raised: %s", exc,
            )
            queue = None

    signals: dict[str, Any] = {
        "executed": 0,
        "failed": 0,
        "pending": 0,
        "outcome_score": None,
        "positive_count": 0,
        "negative_count": 0,
        "alert_streak_7d": 0,
        "alert_paused": False,
        "exempt": False,
        "released": False,
        "last_alert_at": None,
    }

    if queue is not None:
        try:
            stats = queue.stats_by_engine() or {}
            per_engine = stats.get(engine, {}) or {}
            signals["executed"] = int(per_engine.get("executed", 0))
            signals["failed"] = int(per_engine.get("failed", 0))
            signals["pending"] = int(per_engine.get("pending", 0))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine_health stats_by_engine raised: %s", exc,
            )
        try:
            outcomes = queue.engine_outcome_stats(engine) or {}
            signals["outcome_score"] = outcomes.get("outcome_score")
            signals["positive_count"] = int(
                outcomes.get("positive_count", 0),
            )
            signals["negative_count"] = int(
                outcomes.get("negative_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "engine_health engine_outcome_stats raised: %s",
                exc,
            )

    try:
        from core.approval import quarantine
        state = quarantine.load_state()
        signals["exempt"] = state.is_exempt(engine)
        signals["released"] = state.is_released(engine)
        signals["alert_paused"] = state.is_alert_paused(engine)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine_health quarantine load_state raised: %s", exc,
        )

    try:
        from core.approval import alert_history
        consecutive = (
            alert_history.consecutive_runs_per_engine(
                window_seconds=86400.0 * 7.0,
                now=now,
            )
        )
        signals["alert_streak_7d"] = int(consecutive.get(engine, 0))
        # Newest-first; the first event matching this engine is
        # the most recent.
        for e in alert_history.recent_history(
            since_seconds=86400.0 * 365.0,
            now=now,
        ):
            if e.engine == engine:
                signals["last_alert_at"] = float(e.recorded_at)
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "engine_health alert_history raised: %s", exc,
        )

    score, concerns = _score_from_signals(signals)
    verdict = _verdict_from_score(score)
    return EngineHealth(
        engine=engine,
        score=score,
        verdict=verdict,
        signals=signals,
        concerns=concerns,
    )


def _score_from_signals(
    signals: dict[str, Any],
) -> tuple[int, list[str]]:
    """Apply the deterministic scoring rules.

    Returns ``(score, concerns)`` with score clamped to [1, 10].
    """
    score = 10
    concerns: list[str] = []

    if signals.get("alert_paused"):
        score -= 4
        concerns.append("engine is alert_paused")

    streak = int(signals.get("alert_streak_7d", 0) or 0)
    if streak > 0:
        penalty = min(4, 2 * streak)
        score -= penalty
        concerns.append(
            f"alert streak {streak} day(s) in last 7d"
        )

    polarised = (
        int(signals.get("positive_count", 0) or 0)
        + int(signals.get("negative_count", 0) or 0)
    )
    outcome_score = signals.get("outcome_score")
    if (
        outcome_score is not None
        and polarised >= 5
        and float(outcome_score) < 0.4
    ):
        score -= 2
        concerns.append(
            f"outcome score {float(outcome_score):.0%} "
            "(below 40%)"
        )

    executed = int(signals.get("executed", 0) or 0)
    failed = int(signals.get("failed", 0) or 0)
    recent_total = executed + failed
    if recent_total >= 5:
        failure_rate = failed / recent_total
        if failure_rate >= 0.30:
            score -= 1
            concerns.append(
                f"failure rate {failure_rate:.0%} "
                "({failed} of {recent_total})".format(
                    failure_rate=failure_rate,
                    failed=failed,
                    recent_total=recent_total,
                )
            )

    if signals.get("released"):
        score -= 1
        concerns.append(
            "engine is on the released list "
            "(prior quarantine; monitor closely)"
        )

    if (
        outcome_score is not None
        and polarised >= 5
        and float(outcome_score) >= 0.7
    ):
        score += 1
        # Strong positive signal -- no concern added.

    if score < 1:
        score = 1
    if score > 10:
        score = 10
    return score, concerns


def _verdict_from_score(score: int) -> str:
    if score >= 8:
        return "healthy"
    if score >= 5:
        return "warning"
    return "unhealthy"
