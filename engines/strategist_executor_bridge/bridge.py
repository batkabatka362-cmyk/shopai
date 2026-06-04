"""Map per-store strategist recommendation → plan template
→ plan_executor.

The mapping is deterministic + small, capturing the most
common cases. Falls back to "skip" when the recommendation
doesn't match a known signal.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# source_signal → plan template name
_SIGNAL_TO_TEMPLATE: dict[str, str] = {
    "cold_start":         "cold_start",
    "funnel":             "increase_conversion",
    "trajectory":         "diagnose",
    "trajectory_funnel":  "increase_traffic",
    "checkup":            "diagnose",
    "autonomy":           "diagnose",
    "catch_all_earning":  "retain_customers",
    "catch_all_quiet":    "diagnose",
}


@dataclass
class BridgeDecision:
    store_id: str
    verdict: str = "skip"   # composed / enqueued / skip / error
    top_action: str = ""
    top_impact: str = "low"
    top_confidence: float = 0.0
    source_signal: str = ""
    matched_template: str = ""
    score: float = 0.0
    plan_id: str = ""
    enqueued_count: int = 0
    skip_reason: str = ""


@dataclass
class BridgeReport:
    confirmed: bool
    confidence_floor: float
    store_filter: str
    total_stores_scanned: int = 0
    decisions: list[BridgeDecision] = field(default_factory=list)
    enqueued_total: int = 0
    composed_only: int = 0
    skip_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _bump_skip(report: BridgeReport, reason: str) -> None:
    report.skip_count += 1
    report.skip_reasons[reason] = (
        report.skip_reasons.get(reason, 0) + 1
    )


def _impact_score(impact: str) -> float:
    return {
        "high": 1.0, "medium": 0.6, "low": 0.3,
    }.get(impact, 0.5)


def _list_fleet_stores() -> list[str]:
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        out: list[str] = []
        for s in (sm.list_stores() or []):
            if not isinstance(s, dict):
                continue
            sid = s.get("store_id")
            if sid and sid not in out:
                out.append(sid)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "strategist_bridge: store listing raised: %s",
            exc,
        )
        return []


def _strategist_for_store(
    store_id: str,
) -> dict[str, Any] | None:
    """Run store_strategist for one store. Returns the data
    envelope or None on failure."""
    try:
        from engines.store_strategist import (
            StoreStrategistEngine,
        )
        from core.context.active_store import active_store
        with active_store(store_id):
            result = StoreStrategistEngine().run({
                "data": {"store_id": store_id},
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "strategist_bridge: %s strategist raised: %s",
            store_id, exc,
        )
        return None
    if result.get("status") != "success":
        return None
    return result.get("data") or {}


def _execute_template(
    template: str,
    *,
    store_id: str,
    confirmed: bool,
) -> tuple[str, int, str]:
    """Call plan_executor for the template. Returns
    (plan_id, enqueued_count, skip_reason)."""
    try:
        from engines.plan_executor.executor import execute_plan
        report = execute_plan(
            goal=template,
            store_id=store_id,
            confirmed=confirmed,
        )
        return (
            report.plan_id,
            report.enqueued_count,
            "" if report.enqueued_count > 0 or not confirmed
            else "no_steps_enqueued",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "strategist_bridge: execute_plan raised: %s", exc,
        )
        return ("", 0, f"executor_error: {type(exc).__name__}")


def run_bridge(
    *,
    confirmed: bool,
    confidence_floor: float = 0.6,
    store_filter: str = "",
) -> BridgeReport:
    """Bridge strategist → plan_executor across the fleet."""
    report = BridgeReport(
        confirmed=confirmed,
        confidence_floor=max(0.0, min(1.0, confidence_floor)),
        store_filter=store_filter,
    )

    if store_filter:
        store_ids = [store_filter]
    else:
        store_ids = _list_fleet_stores()
    report.total_stores_scanned = len(store_ids)

    for sid in store_ids:
        data = _strategist_for_store(sid)
        if data is None:
            decision = BridgeDecision(
                store_id=sid, skip_reason="strategist_failed",
                verdict="error",
            )
            report.decisions.append(decision)
            _bump_skip(report, "strategist_failed")
            continue
        recs = data.get("recommendations") or []
        if not recs:
            decision = BridgeDecision(
                store_id=sid, skip_reason="no_recommendations",
            )
            report.decisions.append(decision)
            _bump_skip(report, "no_recommendations")
            continue
        top = recs[0]
        confidence = float(top.get("confidence") or 0.0)
        impact = str(top.get("impact") or "low")
        source = str(top.get("source_signal") or "")
        score = confidence * _impact_score(impact)
        decision = BridgeDecision(
            store_id=sid,
            top_action=str(top.get("action") or ""),
            top_impact=impact,
            top_confidence=confidence,
            source_signal=source,
            score=round(score, 3),
        )

        # Threshold check
        if score < report.confidence_floor:
            decision.skip_reason = "below_floor"
            report.decisions.append(decision)
            _bump_skip(report, "below_floor")
            continue

        # Template lookup
        template = _SIGNAL_TO_TEMPLATE.get(source)
        if not template:
            decision.skip_reason = "no_template_for_signal"
            report.decisions.append(decision)
            _bump_skip(report, "no_template_for_signal")
            continue
        decision.matched_template = template

        # Execute (compose-only in dry-run; enqueue in live)
        plan_id, enq, exec_skip = _execute_template(
            template, store_id=sid, confirmed=confirmed,
        )
        decision.plan_id = plan_id
        decision.enqueued_count = enq
        if exec_skip:
            decision.skip_reason = exec_skip
            decision.verdict = "error"
            report.decisions.append(decision)
            _bump_skip(report, exec_skip)
            continue
        if confirmed:
            decision.verdict = (
                "enqueued" if enq > 0 else "composed"
            )
            report.enqueued_total += enq
        else:
            decision.verdict = "composed"
            report.composed_only += 1
        report.decisions.append(decision)

    return report


def signal_template_map() -> dict[str, str]:
    return dict(_SIGNAL_TO_TEMPLATE)
