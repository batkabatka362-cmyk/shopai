"""Apply transfer candidates as PENDING approvals across the
fleet.

For each candidate:
  1. Look up source store's most recent EXECUTED template
     action (engine + action_type)
  2. Probe target store to confirm same (engine, action_type)
     isn't already enqueued in any status
  3. Enqueue PENDING action on target store with template
     params + a narrative tagging the transfer
  4. Record per-application result for the fleet report
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppliedTransfer:
    from_store: str
    to_store: str
    engine: str
    action_type: str
    capability: str
    enqueued: bool = False
    action_id: str = ""
    skip_reason: str = ""
    score: float = 0.0


@dataclass
class FleetTransferReport:
    confirmed: bool
    min_positive: int
    max_per_pair: int
    allow_cross_niche: bool
    candidates_scanned: int = 0
    applied: list[AppliedTransfer] = field(default_factory=list)
    enqueued_count: int = 0
    skip_count: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)


def _store_niches() -> dict[str, str]:
    try:
        from data_pipeline.store.store_manager import StoreManager
        sm = StoreManager()
        out: dict[str, str] = {}
        for s in (sm.list_stores() or []):
            if not isinstance(s, dict):
                continue
            sid = s.get("store_id")
            niche = (s.get("niche") or "").strip().lower()
            if sid:
                out[sid] = niche
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_transfer_auto: niche lookup raised: %s", exc,
        )
        return {}


def _scan_candidates(
    *,
    min_positive: int,
    same_niche_only: bool,
    top_k: int,
) -> list[Any]:
    """Pull transfer candidates from the existing scanner."""
    try:
        from engines._transfer_scanner import scan_empire_transfers
        from core.approval.queue import get_approval_queue
        report = scan_empire_transfers(
            queue=get_approval_queue(),
            stores=None,
            min_positive_outcomes=min_positive,
            top_k=top_k,
            same_niche_only=same_niche_only,
            store_niches=_store_niches() or None,
        )
        return list(getattr(report, "candidates", []) or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_transfer_auto: scan raised: %s", exc,
        )
        return []


def _candidate_already_on_target(
    queue: Any,
    *,
    engine: str,
    action_type: str,
    target_store: str,
) -> bool:
    """Probe target store across all status buckets for an
    existing (engine, action_type) action."""
    try:
        from core.approval.queue import ApprovalStatus
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_transfer_auto: status import raised: %s", exc,
        )
        return False

    for status in (
        ApprovalStatus.EXECUTED, ApprovalStatus.FAILED,
        ApprovalStatus.PENDING, ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
    ):
        try:
            existing = queue.list_by_status(
                status, engine=engine,
                store_id=target_store, limit=200,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "fleet_transfer_auto: target probe raised: %s",
                exc,
            )
            continue
        if any(
            getattr(a, "action_type", None) == action_type
            for a in existing
        ):
            return True
    return False


def _resolve_template(
    queue: Any,
    *,
    engine: str,
    action_type: str,
    from_store: str,
) -> Any | None:
    """Find the most recent EXECUTED action on source for the
    transfer template. Returns None if missing."""
    try:
        from core.approval.queue import ApprovalStatus
        source_actions = queue.list_by_status(
            ApprovalStatus.EXECUTED,
            engine=engine,
            store_id=from_store,
            limit=200,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_transfer_auto: template lookup raised: %s",
            exc,
        )
        return None
    for a in source_actions:
        if getattr(a, "action_type", None) == action_type:
            return a
    return None


def apply_fleet_transfers(
    *,
    confirmed: bool,
    min_positive: int = 3,
    max_per_pair: int = 5,
    allow_cross_niche: bool = False,
    top_k: int = 50,
) -> FleetTransferReport:
    """Scan the empire + enqueue eligible transfers on each
    target store."""
    report = FleetTransferReport(
        confirmed=confirmed,
        min_positive=min_positive,
        max_per_pair=max_per_pair,
        allow_cross_niche=allow_cross_niche,
    )

    candidates = _scan_candidates(
        min_positive=min_positive,
        same_niche_only=(not allow_cross_niche),
        top_k=top_k,
    )
    report.candidates_scanned = len(candidates)
    if not candidates:
        return report

    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "fleet_transfer_auto: queue import raised: %s", exc,
        )
        return report

    # Track per-pair enqueue count to enforce max_per_pair.
    pair_counts: dict[tuple[str, str], int] = {}

    for cand in candidates:
        from_store = getattr(cand, "from_store", "") or ""
        to_store = getattr(cand, "to_store", "") or ""
        engine = getattr(cand, "engine", "") or ""
        action_type = getattr(cand, "action_type", "") or ""
        capability = getattr(cand, "capability", "") or ""
        score = float(getattr(cand, "score", 0.0) or 0.0)

        applied = AppliedTransfer(
            from_store=from_store,
            to_store=to_store,
            engine=engine,
            action_type=action_type,
            capability=capability,
            score=score,
        )

        # Bail early if any identifier missing.
        if not (from_store and to_store and engine and action_type):
            applied.skip_reason = "missing_fields"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue
        if from_store == to_store:
            applied.skip_reason = "same_store"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue

        pair = (from_store, to_store)
        if pair_counts.get(pair, 0) >= max_per_pair:
            applied.skip_reason = "pair_cap"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue

        if _candidate_already_on_target(
            queue,
            engine=engine,
            action_type=action_type,
            target_store=to_store,
        ):
            applied.skip_reason = "already_on_target"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue

        template = _resolve_template(
            queue,
            engine=engine,
            action_type=action_type,
            from_store=from_store,
        )
        if template is None:
            applied.skip_reason = "no_template"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue

        if not confirmed:
            applied.skip_reason = "dry_run"
            report.applied.append(applied)
            report.skip_count += 1
            report.skip_reasons[applied.skip_reason] = (
                report.skip_reasons.get(applied.skip_reason, 0)
                + 1
            )
            continue

        narrative = (
            f"Fleet-auto transfer: {engine}/{action_type} "
            f"from {from_store} -> {to_store} "
            f"(score={score:.2f})"
        )

        try:
            action = queue.enqueue(
                engine=engine,
                action_type=action_type,
                capability=capability or getattr(
                    template, "capability", "",
                ),
                params=dict(
                    getattr(template, "params", None) or {},
                ),
                narrative=narrative,
                store_id=to_store,
            )
            applied.enqueued = True
            applied.action_id = str(
                getattr(action, "id", "") or "",
            )
            report.enqueued_count += 1
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
        except Exception as exc:  # noqa: BLE001
            applied.skip_reason = (
                f"enqueue_failed: {type(exc).__name__}"
            )
            report.skip_count += 1
            report.skip_reasons["enqueue_failed"] = (
                report.skip_reasons.get("enqueue_failed", 0)
                + 1
            )

        report.applied.append(applied)

    return report
