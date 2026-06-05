"""Compose every Phase 3 substrate into one morning brief."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

# W963-92: canonical Pattern J guard
from core.agi.persistence import (
    is_test_environment as _is_test_environment,
)

logger = logging.getLogger(__name__)


@dataclass
class MorningBrief:
    store_id: str
    verdict: str = "no_data"
    gross_profit: float = 0.0
    attribution_pct: float = 0.0
    monthly_run_rate: float = 0.0
    trend_band: str = "no_data"   # rising/falling/flat/no_data
    history_trend_verdict: str = "no_data"
    history_samples: int = 0
    orphan_action_count: int = 0
    pending_approvals: int = 0
    last_cycle_age_hours: float = 0.0
    last_cycle_verdict: str = "unknown"
    proposed: list[dict[str, Any]] = field(
        default_factory=list,
    )
    critiques: list[dict[str, Any]] = field(
        default_factory=list,
    )
    snapshot_recorded: bool = False
    anomalies: list[dict[str, Any]] = field(
        default_factory=list,
    )
    anomaly_critical_count: int = 0
    # W963-69: brief-diff context
    diff_direction: str = "no_data"
    diff_headline: str = ""
    diff_gross_profit_delta: float = 0.0
    # W963-71: attention streak context
    attention_needed: bool = False
    attention_top_streak: str = ""
    attention_top_count: int = 0
    attention_top_severity: str = "info"
    # W963-81: arm recommender override surface
    arm_override_active: str | None = None
    arm_recommended_count: int = 0
    arm_disarm_count: int = 0
    # W963-89: earn-path on-ramp progress
    earn_path_completed: int = 0
    earn_path_total: int = 0
    earn_path_next_command: str | None = None
    earn_path_next_title: str | None = None
    headline: str = ""
    next_action: str = ""


# W963-92: _is_test_environment imported from core.agi.persistence.


def _gather_summary(brief: MorningBrief) -> None:
    try:
        from engines.agi_earnings_summary.summarizer import (
            compute_summary,
        )
        s = compute_summary(days=7)
        brief.verdict = s.verdict
        brief.gross_profit = s.fleet_gross_profit
        brief.attribution_pct = s.fleet_attribution_pct
        brief.monthly_run_rate = s.monthly_run_rate
        brief.trend_band = s.trend_verdict
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: summary raised: %s", exc)


def _gather_history_trend(brief: MorningBrief) -> None:
    try:
        from engines.agi_earnings_history import store as h
        t = h.compute_trend(days=14)
        brief.history_trend_verdict = str(
            t.get("verdict", "no_data"),
        )
        brief.history_samples = int(
            t.get("sample_count", 0) or 0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: history raised: %s", exc)


def _gather_recon(brief: MorningBrief) -> None:
    try:
        from engines.revenue_reconciliation.reconciler import (
            reconcile_fleet,
        )
        r = reconcile_fleet(days=7)
        brief.orphan_action_count = (
            r.fleet_orphan_action_count
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: recon raised: %s", exc)


def _gather_approvals(brief: MorningBrief) -> None:
    try:
        from core.approval.queue import get_approval_queue
        q = get_approval_queue()
        brief.pending_approvals = len(
            q.list_by_status("pending") or [],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: approvals raised: %s", exc)


def _gather_last_cycle(brief: MorningBrief) -> None:
    try:
        from engines._cycle_history import last_run
        last = last_run()
        if last is None:
            return
        # cycle_history records use 'started_at'
        ts = (
            getattr(last, "started_at", None)
            or getattr(last, "ended_at", None)
            or getattr(last, "ts", None)
        )
        if ts is None:
            return
        import time
        try:
            age = max(
                0.0, (time.time() - float(ts)) / 3600.0,
            )
        except (TypeError, ValueError):
            return
        brief.last_cycle_age_hours = round(age, 1)
        brief.last_cycle_verdict = str(
            getattr(last, "verdict", "unknown"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: cycle raised: %s", exc)


def _gather_proposals(brief: MorningBrief) -> None:
    try:
        from engines.llm_action_proposer.proposer import (
            propose,
        )
        rp = propose(store_id=brief.store_id)
        brief.proposed = [
            {
                "rank": a.rank,
                "action": a.action,
                "cli_command": a.cli_command,
                "rationale": a.rationale,
                "priority": a.priority,
            }
            for a in rp.proposed
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: proposer raised: %s", exc)


def _gather_critiques(brief: MorningBrief) -> None:
    if not brief.proposed:
        return
    try:
        from engines.llm_action_critic.critic import (
            critique,
        )
        rc = critique(
            proposed_override=brief.proposed,
            verdict_override=brief.verdict,
        )
        brief.critiques = [
            {
                "rank": c.rank,
                "severity": c.severity,
                "risk_flags": c.risk_flags,
                "counter_rationale": c.counter_rationale,
            }
            for c in rc.critiques
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: critic raised: %s", exc)


def _maybe_record_snapshot(
    brief: MorningBrief, persist: bool,
) -> None:
    if not persist:
        return
    if _is_test_environment():
        return
    try:
        from engines.agi_earnings_history import store as h
        import time
        snapshot = {
            "ts": time.time(),
            "days": 7,
            "verdict": brief.verdict,
            "gross_profit": brief.gross_profit,
            "attribution_pct": brief.attribution_pct,
            "monthly_run_rate": brief.monthly_run_rate,
            "trend_verdict": brief.trend_band,
            "store_count": 0,
        }
        wrote = h.record_snapshot(snapshot)
        brief.snapshot_recorded = bool(wrote)
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: record raised: %s", exc)


def _build_headline(brief: MorningBrief) -> str:
    v = brief.verdict
    if v == "no_data":
        return (
            "Empire IDLE -- no revenue in 7d window."
        )
    if v == "attributed_loss":
        # W963-93: render -$X instead of $-X when profit < 0.
        sign = "-" if brief.gross_profit < 0 else ""
        return (
            f"Empire BLEEDING -- "
            f"{sign}${abs(brief.gross_profit):.0f} fleet loss "
            f"(AGI attributing "
            f"{brief.attribution_pct:.0f}%)."
        )
    if v == "organic_only":
        # gross_profit is usually positive in organic_only,
        # but render sign-prefix-before-$ in case of edge.
        sign = "-" if brief.gross_profit < 0 else ""
        return (
            "Empire EARNING but AGI not attributed -- "
            f"{sign}${abs(brief.gross_profit):.0f} profit, "
            "0% AGI."
        )
    # earning
    arrow = {
        "improving": " UP",
        "declining": " DOWN",
        "flat":      "",
        "no_data":   "",
    }.get(brief.history_trend_verdict, "")
    return (
        f"Empire EARNING{arrow} -- "
        f"${brief.gross_profit:.0f} profit, "
        f"{brief.attribution_pct:.0f}% AGI, "
        f"${brief.monthly_run_rate:.0f}/mo run-rate."
    )


def _build_next_action(brief: MorningBrief) -> str:
    # Critical streaks escalate ABOVE single-cycle anomalies
    # because they mean "I've been warning for N cycles in
    # a row -- operator hasn't listened".
    if (
        brief.attention_needed
        and brief.attention_top_severity == "critical"
    ):
        return (
            f"CRITICAL streak {brief.attention_top_streak} "
            f"= {brief.attention_top_count} cycles. "
            "shopai attention for full triple."
        )
    # Critical anomalies escalate above the proposer plan
    if brief.anomaly_critical_count > 0:
        crit = next(
            (
                a for a in brief.anomalies
                if a.get("severity") == "critical"
            ),
            None,
        )
        if crit:
            return (
                f"CRITICAL anomaly {crit.get('type')}: "
                "run shopai anomalies before plan."
            )
    if not brief.proposed:
        return "No next-action proposed."
    top = brief.proposed[0]
    # Find matching critique
    top_crit = None
    for c in brief.critiques:
        if c.get("rank") == top.get("rank"):
            top_crit = c
            break
    sev = (
        top_crit.get("severity", "info")
        if top_crit else "info"
    )
    sev_tag = (
        " [CRITICAL]"
        if sev == "critical"
        else " [WARN]"
        if sev == "warn"
        else ""
    )
    return (
        f"#1{sev_tag}: {top.get('action', '?')} -> "
        f"{top.get('cli_command', '')}"
    )


def _gather_attention_streak(brief: MorningBrief) -> None:
    try:
        from engines.agi_recommend_streak.detector import (
            detect_streaks,
        )
        r = detect_streaks(threshold_days=3)
        brief.attention_needed = r.attention_needed
        if r.attention_needed and r.top_streak:
            brief.attention_top_streak = r.top_streak
            top = getattr(r, r.top_streak, None)
            if top is not None:
                brief.attention_top_count = top.count
                brief.attention_top_severity = top.severity
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: attention raised: %s", exc,
        )


def _gather_earn_path(brief: MorningBrief) -> None:
    """W963-89: surface on-ramp progress when incomplete."""
    try:
        from engines.earn_path.guide import build_path
        report = build_path()
        brief.earn_path_completed = report.completed_count
        brief.earn_path_total = report.total_count
        brief.earn_path_next_command = report.next_command
        brief.earn_path_next_title = report.next_title
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: earn_path raised: %s", exc,
        )


def _gather_arm_recommender(brief: MorningBrief) -> None:
    """W963-81: surface arm-recommender override into the
    morning brief so operator sees it on AM scan."""
    try:
        from engines.agi_arm_recommender.recommender \
            import recommend
        r = recommend()
        brief.arm_override_active = r.override_applied
        brief.arm_recommended_count = len(
            r.arm_recommendations,
        )
        brief.arm_disarm_count = len(
            r.disarm_recommendations,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "brief: arm-recommender raised: %s", exc,
        )


def _gather_brief_diff(brief: MorningBrief) -> None:
    try:
        from engines.agi_brief_diff.differ import (
            compute_diff,
        )
        d = compute_diff()
        brief.diff_direction = d.direction
        brief.diff_headline = d.headline
        brief.diff_gross_profit_delta = (
            d.gross_profit_delta
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: diff raised: %s", exc)


def _gather_anomalies(brief: MorningBrief) -> None:
    try:
        from engines.agi_anomaly_detector.detector import (
            detect,
        )
        r = detect(window=14)
        brief.anomalies = [
            {
                "type": a.type,
                "severity": a.severity,
                "delta": a.delta,
                "description": a.description,
                "occurred_at": a.occurred_at,
            }
            for a in r.anomalies
        ]
        brief.anomaly_critical_count = sum(
            1 for a in r.anomalies
            if a.severity == "critical"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("brief: anomalies raised: %s", exc)


def build_morning_brief(
    *,
    store_id: str = "",
    persist_snapshot: bool = False,
) -> MorningBrief:
    brief = MorningBrief(store_id=store_id)
    _gather_summary(brief)
    _gather_history_trend(brief)
    _gather_recon(brief)
    _gather_approvals(brief)
    _gather_last_cycle(brief)
    _gather_proposals(brief)
    _gather_critiques(brief)
    _gather_anomalies(brief)
    _gather_brief_diff(brief)
    _gather_attention_streak(brief)
    _gather_arm_recommender(brief)
    _gather_earn_path(brief)
    _maybe_record_snapshot(brief, persist_snapshot)
    brief.headline = _build_headline(brief)
    brief.next_action = _build_next_action(brief)
    return brief
