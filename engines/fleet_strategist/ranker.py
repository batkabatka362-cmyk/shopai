"""Fleet-wide ranking.

For each store: run store_strategist, compute fleet_priority.
Stores grouped into:
  - intervene_now: verdict=intervene + revenue>0
  - cold_start:    revenue=0 + few recommendations
  - active:        verdict=active (earning) + nothing critical
  - quiet:         everything else

Within each bucket, sorted by fleet_priority desc.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StoreRanking:
    store_id: str
    niche: str = ""
    verdict: str = "wait"
    top_action: str = ""
    top_drill: str = ""
    top_confidence: float = 0.0
    top_impact: str = "low"
    top_reasoning: str = ""
    urgency_score: float = 0.0
    revenue_7d: float = 0.0
    revenue_weight: float = 0.0
    fleet_priority: float = 0.0
    bucket: str = "quiet"
    recommendation_count: int = 0


@dataclass
class FleetStrategistReport:
    total_stores: int = 0
    stores_with_data: int = 0
    by_bucket: dict[str, list[StoreRanking]] = field(
        default_factory=dict,
    )
    all_rankings: list[StoreRanking] = field(default_factory=list)
    verdict_filter: str = ""
    top_filter: int = 0


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
            "fleet_strategist: store listing raised: %s",
            exc,
        )
        return []


def _bucket_for(
    verdict: str,
    revenue: float,
    rec_count: int,
) -> str:
    if verdict == "intervene" and revenue > 0.0:
        return "intervene_now"
    if revenue == 0.0 and rec_count <= 3:
        return "cold_start"
    if verdict == "active":
        return "active"
    return "quiet"


def _rank_one_store(store_id: str) -> StoreRanking | None:
    """Run store_strategist for one store + extract ranking
    signals. Wrapped in try/except per-store so a bad store
    doesn't halt the fleet loop."""
    try:
        from engines.store_strategist import (
            StoreStrategistEngine,
        )
        from core.context.active_store import active_store
        with active_store(store_id):
            result = StoreStrategistEngine().run({
                "data": {"store_id": store_id},
            })
        if result.get("status") != "success":
            return None
        data = result.get("data") or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_strategist: store %s raised: %s",
            store_id, exc,
        )
        return None

    ctx = data.get("context") or {}
    recs = data.get("recommendations") or []
    top = recs[0] if recs else {}

    revenue = float(ctx.get("total_revenue_7d") or 0.0)
    urgency = float(top.get("priority_score") or 0.0)
    revenue_weight = math.log10(revenue + 10.0)
    fleet_priority = urgency * revenue_weight

    ranking = StoreRanking(
        store_id=store_id,
        niche=str(data.get("niche") or ""),
        verdict=str(data.get("verdict") or "wait"),
        top_action=str(top.get("action") or ""),
        top_drill=str(top.get("drill_command") or ""),
        top_confidence=float(top.get("confidence") or 0.0),
        top_impact=str(top.get("impact") or "low"),
        top_reasoning=str(top.get("reasoning") or ""),
        urgency_score=round(urgency, 3),
        revenue_7d=round(revenue, 2),
        revenue_weight=round(revenue_weight, 3),
        fleet_priority=round(fleet_priority, 4),
        bucket=_bucket_for(
            data.get("verdict") or "wait",
            revenue,
            len(recs),
        ),
        recommendation_count=len(recs),
    )
    return ranking


def _sort_within_bucket(
    rankings: list[StoreRanking],
) -> list[StoreRanking]:
    return sorted(
        rankings,
        key=lambda r: (r.fleet_priority, r.urgency_score),
        reverse=True,
    )


def rank_fleet(
    *,
    verdict_filter: str = "",
    top: int = 0,
) -> FleetStrategistReport:
    """Rank every store in the fleet."""
    report = FleetStrategistReport(
        verdict_filter=verdict_filter,
        top_filter=top,
    )
    store_ids = _list_fleet_stores()
    report.total_stores = len(store_ids)

    all_rankings: list[StoreRanking] = []
    for sid in store_ids:
        ranking = _rank_one_store(sid)
        if ranking is None:
            continue
        if (
            verdict_filter
            and ranking.verdict != verdict_filter
        ):
            continue
        all_rankings.append(ranking)

    report.stores_with_data = len(all_rankings)

    # Group + sort each bucket
    buckets: dict[str, list[StoreRanking]] = {
        "intervene_now": [],
        "cold_start":    [],
        "active":        [],
        "quiet":         [],
    }
    for r in all_rankings:
        buckets[r.bucket].append(r)
    for k, v in buckets.items():
        buckets[k] = _sort_within_bucket(v)

    report.by_bucket = buckets

    # Flatten in display order: intervene → active → cold → quiet
    flat: list[StoreRanking] = []
    for bucket_name in (
        "intervene_now", "active", "cold_start", "quiet",
    ):
        flat.extend(buckets[bucket_name])

    if top > 0:
        flat = flat[:top]
    report.all_rankings = flat
    return report


def overall_verdict(
    report: FleetStrategistReport,
) -> str:
    """Top-line verdict for the fleet."""
    if report.stores_with_data == 0:
        return "no_data"
    intervene = len(report.by_bucket.get("intervene_now", []))
    active = len(report.by_bucket.get("active", []))
    cold = len(report.by_bucket.get("cold_start", []))
    if intervene > 0:
        return "intervention_needed"
    if active > 0 and active >= report.stores_with_data // 2:
        return "earning_fleet"
    if cold > 0:
        return "cold_start_fleet"
    return "quiet_fleet"
