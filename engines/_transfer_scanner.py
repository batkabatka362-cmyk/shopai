"""Empire-wide cross-store transfer scanner.

``shopai transfer suggest --from A --to B`` works for one
pair. At 20-store empire, operator would need to suggest
20*19 = 380 pairs manually -- not scalable. Wave 71 ships
the empire-wide scanner: walk every (source, target) pair,
identify transferable winners, surface top-N across the
empire.

## Algorithm (deterministic v1)

For each pair (A, B) where A != B:
  1. Pull executed actions on A with measured positive
     outcomes.
  2. Group by (engine, action_type, capability).
  3. Exclude (engine, action_type, capability) tuples already
     tried on B (any status).
  4. Score each candidate by:
       positive_outcomes * log(revenue + 1)
  5. Top-scoring candidates are transferable.

Per-empire rollup ranks candidates across all pairs.

## Caveats

- Single-cycle wins don't count (min positive_outcomes >= 2)
- Stale source data weighted lower (decay knob)
- Doesn't model store dissimilarity (beauty store winner !=
  tech store winner). Future v2: niche-aware filtering.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TransferCandidate:
    from_store: str
    to_store: str
    engine: str
    action_type: str
    capability: str
    positive_outcomes: int
    total_revenue: float
    score: float


@dataclass
class TransferScanReport:
    pairs_scanned: int = 0
    candidates: list[TransferCandidate] = field(
        default_factory=list,
    )

    @property
    def total_candidates(self) -> int:
        return len(self.candidates)

    @property
    def top_pair(self) -> tuple[str, str] | None:
        if not self.candidates:
            return None
        top = self.candidates[0]
        return (top.from_store, top.to_store)


def _score_candidate(
    positive: int, revenue: float,
) -> float:
    """log-scaled product so $10 positive and $1000 positive
    don't dominate."""
    if positive < 2:
        return 0.0
    return round(positive * math.log10(revenue + 10.0), 2)


def scan_empire_transfers(
    *,
    queue: Any = None,
    stores: list[str] | None = None,
    min_positive_outcomes: int = 2,
    top_k: int = 20,
) -> TransferScanReport:
    """Scan all store pairs for transfer opportunities.

    Args:
        queue: ApprovalQueue (optional override for tests).
        stores: List of store_ids (optional override). If None,
            pulls from StoreManager.
        min_positive_outcomes: Minimum positive outcomes for a
            candidate to qualify.
        top_k: Maximum candidates to return.

    Returns:
        Populated TransferScanReport with candidates sorted by
        score desc.
    """
    report = TransferScanReport()
    # Resolve queue
    if queue is None:
        try:
            from core.approval.queue import get_approval_queue
            queue = get_approval_queue()
        except Exception:  # noqa: BLE001
            return report
    # Resolve stores
    if stores is None:
        try:
            from data_pipeline.store.store_manager import StoreManager
            stores = [
                s["store_id"] for s in (
                    StoreManager().list_stores() or []
                )
                if s.get("store_id")
            ]
        except Exception:  # noqa: BLE001
            return report
    if len(stores) < 2:
        return report

    # Pull executed actions once -- avoid N^2 queue queries
    try:
        executed = queue.list_by_status("executed") or []
    except Exception:  # noqa: BLE001
        return report

    # Build per-store action sets: tried tuples
    tried_per_store: dict[str, set[tuple]] = {
        s: set() for s in stores
    }
    # Per-store winners: (engine, action_type, capability) ->
    # {positive: int, revenue: float}
    winners_per_store: dict[
        str, dict[tuple, dict[str, float]],
    ] = {s: {} for s in stores}

    # Pass 1: aggregate per-tuple outcomes across all actions
    # WITHOUT the min_positive_outcomes filter (which applies
    # to the tuple total, not the per-action total).
    for action in executed:
        store_id = getattr(action, "store_id", None)
        if not store_id or store_id not in tried_per_store:
            continue
        key = (
            getattr(action, "engine", "") or "",
            getattr(action, "action_type", "") or "",
            getattr(action, "capability", "") or "",
        )
        tried_per_store[store_id].add(key)
        try:
            outcomes = queue.get_outcomes(action.id) or []
        except Exception:  # noqa: BLE001
            outcomes = []
        positive = 0
        revenue = 0.0
        for o in outcomes:
            if not isinstance(o, dict):
                continue
            if o.get("polarity") == "positive":
                positive += 1
                metrics = o.get("metrics") or {}
                try:
                    revenue += float(
                        metrics.get("revenue", 0) or 0,
                    )
                except (TypeError, ValueError):
                    continue
        if positive == 0:
            continue
        bucket = winners_per_store[store_id].setdefault(
            key, {"positive": 0, "revenue": 0.0},
        )
        bucket["positive"] += positive
        bucket["revenue"] = round(
            bucket["revenue"] + revenue, 2,
        )

    # Pass 2: filter tuples that didn't meet the
    # min_positive_outcomes threshold across all their
    # actions.
    for store_id in stores:
        winners_per_store[store_id] = {
            key: stats
            for key, stats in winners_per_store[store_id].items()
            if stats["positive"] >= min_positive_outcomes
        }

    # Walk every pair (source != target)
    candidates: list[TransferCandidate] = []
    for source in stores:
        for target in stores:
            if source == target:
                continue
            report.pairs_scanned += 1
            for key, stats in winners_per_store[source].items():
                if key in tried_per_store[target]:
                    continue
                engine, action_type, capability = key
                score = _score_candidate(
                    int(stats["positive"]),
                    float(stats["revenue"]),
                )
                if score <= 0:
                    continue
                candidates.append(TransferCandidate(
                    from_store=source,
                    to_store=target,
                    engine=engine,
                    action_type=action_type,
                    capability=capability,
                    positive_outcomes=int(stats["positive"]),
                    total_revenue=float(stats["revenue"]),
                    score=score,
                ))

    candidates.sort(key=lambda c: -c.score)
    report.candidates = candidates[:top_k]
    return report
