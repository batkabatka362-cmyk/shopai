"""Iterate autopilot across the fleet.

For each store:
  1. Enter active_store(sid) context
  2. Run autopilot.run_autopilot(confirmed=, store_id=sid)
  3. Capture per-store StageResult list + verdict
  4. Exit context

Aggregates per-store reports into a single FleetReport with:
  - total_stores
  - overall_verdict (worst per-store verdict)
  - by_store: list of {store_id, verdict, stages_summary}
  - sent_count_total: emails actually dispatched
  - errors_total: stage errors across the fleet
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StoreOutcome:
    store_id: str
    verdict: str = "skipped"  # ok / warn / error / disabled / skipped
    stages: list[dict[str, Any]] = field(default_factory=list)
    sent_count: int = 0
    failed_count: int = 0
    fired_count: int = 0
    error_count: int = 0


@dataclass
class FleetReport:
    confirmed: bool
    only_store: str | None
    skipped_stores: list[str] = field(default_factory=list)
    total_stores: int = 0
    by_store: list[StoreOutcome] = field(default_factory=list)
    overall_verdict: str = "skipped"
    sent_count_total: int = 0
    errors_total: int = 0


def _list_fleet() -> list[str]:
    """Best-effort fleet listing. Returns ids only."""
    try:
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        stores = sm.list_stores() or []
        ids = []
        for s in stores:
            sid = s.get("store_id") if isinstance(s, dict) else None
            if sid and sid not in ids:
                ids.append(sid)
        return ids
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_autopilot: store listing raised: %s", exc,
        )
        return []


def _run_one_store(
    store_id: str, *, confirmed: bool,
) -> StoreOutcome:
    """Run autopilot for one store inside its active_store
    context. Wraps in try/except so a single bad store
    doesn't halt the fleet loop."""
    outcome = StoreOutcome(store_id=store_id)
    try:
        from core.context.active_store import active_store
        from engines.autopilot.runner import run_autopilot
        with active_store(store_id):
            ap = run_autopilot(
                confirmed=confirmed,
                store_id=store_id,
            )
        outcome.verdict = ap.overall_verdict
        for s in ap.stages:
            stage_data = s.data if isinstance(s.data, dict) else {}
            outcome.stages.append({
                "name": s.name,
                "enabled": s.enabled,
                "fired": s.fired,
                "verdict": s.verdict,
                "detail": s.detail,
            })
            if s.fired:
                outcome.fired_count += 1
            if s.verdict == "error":
                outcome.error_count += 1
            sent = stage_data.get("sent")
            if isinstance(sent, int):
                outcome.sent_count += sent
            failed = stage_data.get("failed")
            if isinstance(failed, int):
                outcome.failed_count += failed
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_autopilot[%s]: raised %s", store_id, exc,
        )
        outcome.verdict = "error"
        outcome.error_count += 1
    return outcome


def _compute_overall(
    outcomes: list[StoreOutcome],
) -> str:
    """Worst per-store verdict wins. Severity order:
    error > warn > ok > disabled > skipped."""
    sev = {
        "error": 0, "warn": 1, "ok": 2,
        "disabled": 3, "skipped": 4,
    }
    worst = "skipped"
    for o in outcomes:
        if sev.get(o.verdict, 4) < sev.get(worst, 4):
            worst = o.verdict
    return worst


def run_fleet_autopilot(
    *,
    confirmed: bool,
    only_store: str | None = None,
    skip_stores: list[str] | None = None,
) -> FleetReport:
    """Execute autopilot per-store across the fleet."""
    report = FleetReport(
        confirmed=confirmed, only_store=only_store,
    )
    skip = set(skip_stores or [])

    if only_store:
        store_ids = [only_store]
    else:
        store_ids = _list_fleet()

    report.total_stores = len(store_ids)

    for sid in store_ids:
        if sid in skip:
            report.skipped_stores.append(sid)
            continue
        outcome = _run_one_store(sid, confirmed=confirmed)
        report.by_store.append(outcome)
        report.sent_count_total += outcome.sent_count
        report.errors_total += outcome.error_count

    report.overall_verdict = _compute_overall(report.by_store)
    return report
