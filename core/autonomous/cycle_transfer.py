"""Cross-store TRANSFER phase for the autonomous cycle.

The cycle's ADVANCE phase walks each store's audit gaps and
executes the plan for closing them. When a store has NO
audit gaps (or refuses on reliability + no plan was
generated), it sits idle for the cycle. The empire-AGI
vision (1 operator + AI = 20+ stores) wants those idle
stores to LEARN from peer stores' wins.

This module is the bridge. For each idle store, walk the
rest of the fleet and find ``(engine, action_type)`` tuples
that:

  - EXECUTED on at least one OTHER store
  - Have NOT been tried on the target store in any status
  - Have positive outcomes / revenue (winners only, not
    just "ran")

Enqueue (don't auto-execute) so operator approval is still
the gate. Adds a queue row the operator reviews via
``shopai approvals show``.

Env-var contract (default OFF for safety):

  - ``SHOPAI_AUTO_TRANSFER=1`` -- enables the bridge.
  - ``SHOPAI_AUTO_TRANSFER_MAX_PER_STORE`` -- max number of
    transfers enqueued per cycle per target store. Default
    3 (conservative -- prevents flooding the approval
    queue).
  - ``SHOPAI_AUTO_TRANSFER_MIN_OUTCOMES`` -- minimum
    positive_outcomes count on the source action before
    it's considered transferable. Default 1.

Pattern J: ``maybe_apply_transfers`` short-circuits under
pytest. ``find_transfer_candidates`` previews always
compute.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_ENV_ENABLED = "SHOPAI_AUTO_TRANSFER"
_ENV_MAX_PER_STORE = "SHOPAI_AUTO_TRANSFER_MAX_PER_STORE"
_ENV_MIN_OUTCOMES = "SHOPAI_AUTO_TRANSFER_MIN_OUTCOMES"

_DEFAULT_MAX_PER_STORE = 3
_DEFAULT_MIN_OUTCOMES = 1


@dataclass
class TransferCandidate:
    """One transfer suggestion. ``source_store_id`` is the
    fleet peer that ran this action successfully;
    ``target_store_id`` is the idle store we'd transfer
    onto."""

    target_store_id: str
    source_store_id: str
    engine: str
    action_type: str
    capability: str
    sample_params: dict[str, Any] = field(
        default_factory=dict,
    )
    source_success_count: int = 0
    positive_outcomes: int = 0
    negative_outcomes: int = 0
    total_revenue: float = 0.0
    source_action_id: str | None = None


def is_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED) == "1"


def max_per_store() -> int:
    raw = os.environ.get(_ENV_MAX_PER_STORE)
    if not raw:
        return _DEFAULT_MAX_PER_STORE
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PER_STORE


def min_outcomes() -> int:
    raw = os.environ.get(_ENV_MIN_OUTCOMES)
    if not raw:
        return _DEFAULT_MIN_OUTCOMES
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MIN_OUTCOMES


def _is_test_environment() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def find_transfer_candidates(
    *,
    target_store_id: str,
    fleet_store_ids: list[str] | None = None,
    max_candidates: int | None = None,
    min_positive_outcomes: int | None = None,
) -> list[TransferCandidate]:
    """Read-only: find transferable wins for the target
    store from anywhere in the fleet.

    Walks every fleet peer's EXECUTED actions, aggregates by
    ``(engine, action_type, capability)``, excludes anything
    already tried on the target, ranks by positive outcomes
    + revenue + success count. Returns top-N.

    Args:
        target_store_id: the store receiving suggestions.
        fleet_store_ids: list of fleet store ids. If
            omitted, queries the store manager for the
            fleet (fail-open: returns [] on failure).
        max_candidates: cap returned candidates. Default:
            env-tuned ``max_per_store()``.
        min_positive_outcomes: skip candidates with fewer
            positive outcomes than this. Default: env-tuned
            ``min_outcomes()``.

    Returns:
        Newest-best-first list of TransferCandidate dicts.
        Empty when no candidates qualify.
    """
    try:
        from core.approval.queue import (
            ApprovalStatus, get_approval_queue,
        )
    except ImportError as exc:
        logger.debug(
            "cycle_transfer: queue import failed: %s",
            exc,
        )
        return []

    if not target_store_id:
        return []

    max_n = (
        max_candidates if max_candidates is not None
        else max_per_store()
    )
    min_pos = (
        min_positive_outcomes
        if min_positive_outcomes is not None
        else min_outcomes()
    )

    if fleet_store_ids is None:
        try:
            from core.adapters.shopify.bootstrap import (
                _get_store_manager_for_tests,
            )
            sm = _get_store_manager_for_tests()
        except ImportError:
            sm = None
        if sm is None:
            try:
                # Most callers will pass fleet_store_ids
                # explicitly; this fallback is for
                # callers that just want "fleet by
                # discovery".
                from core.stores.manager import (
                    StoreManager,
                )
                sm = StoreManager()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "cycle_transfer: store manager "
                    "import raised: %s", exc,
                )
                return []
        try:
            fleet = sm.list_stores() or []
            fleet_store_ids = [
                s.get("store_id")
                for s in fleet
                if s.get("store_id")
            ]
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cycle_transfer: list_stores raised: %s",
                exc,
            )
            return []

    # Exclude the target itself
    peer_ids = [
        sid for sid in (fleet_store_ids or [])
        if sid and sid != target_store_id
    ]
    if not peer_ids:
        return []

    queue = get_approval_queue()

    # Build the target's "already tried" set: any (engine,
    # action_type) tuple in ANY status. Same exclusion
    # semantics as ``transfer suggest``.
    target_tried: set[tuple[str, str]] = set()
    for status in (
        ApprovalStatus.EXECUTED,
        ApprovalStatus.FAILED,
        ApprovalStatus.PENDING,
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    ):
        try:
            rows = queue.list_by_status(
                status,
                store_id=target_store_id,
                limit=2000,
            )
        except TypeError:
            # Pre-#239 queue without store_id kwarg
            logger.debug(
                "cycle_transfer: queue lacks "
                "store_id filter",
            )
            return []
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cycle_transfer: target probe raised: %s",
                exc,
            )
            continue
        for a in rows:
            target_tried.add((a.engine, a.action_type))

    # Aggregate EXECUTED actions from every peer
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for sid in peer_ids:
        try:
            src_rows = queue.list_by_status(
                ApprovalStatus.EXECUTED,
                store_id=sid,
                limit=2000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cycle_transfer: source probe raised: %s",
                exc,
            )
            continue
        for a in src_rows:
            key = (a.engine, a.action_type, a.capability)
            if (a.engine, a.action_type) in target_tried:
                continue
            bucket = groups.setdefault(key, {
                "engine": a.engine,
                "action_type": a.action_type,
                "capability": a.capability,
                "source_store_id": sid,
                "source_action_id": a.id,
                "sample_params": a.params or {},
                "source_success_count": 0,
                "positive_outcomes": 0,
                "negative_outcomes": 0,
                "total_revenue": 0.0,
            })
            bucket["source_success_count"] += 1
            # Outcomes lookup -- best-effort
            try:
                outcomes = queue.get_outcomes(a.id) or []
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "cycle_transfer: outcomes raised: %s",
                    exc,
                )
                outcomes = []
            for o in outcomes:
                polarity = o.get("polarity", "neutral")
                if polarity == "positive":
                    bucket["positive_outcomes"] += 1
                elif polarity == "negative":
                    bucket["negative_outcomes"] += 1
                metrics = o.get("metrics") or {}
                rev = metrics.get("revenue")
                if rev is not None:
                    try:
                        bucket["total_revenue"] += float(rev)
                    except (TypeError, ValueError):
                        pass

    # Filter by min_positive_outcomes, sort, take top-N
    qualifying = [
        b for b in groups.values()
        if b["positive_outcomes"] >= min_pos
    ]
    qualifying.sort(
        key=lambda b: (
            -b["positive_outcomes"],
            -b["total_revenue"],
            -b["source_success_count"],
        ),
    )

    candidates: list[TransferCandidate] = []
    for b in qualifying[:max_n]:
        candidates.append(TransferCandidate(
            target_store_id=target_store_id,
            source_store_id=b["source_store_id"],
            engine=b["engine"],
            action_type=b["action_type"],
            capability=b["capability"],
            sample_params=dict(b["sample_params"] or {}),
            source_success_count=b["source_success_count"],
            positive_outcomes=b["positive_outcomes"],
            negative_outcomes=b["negative_outcomes"],
            total_revenue=b["total_revenue"],
            source_action_id=b["source_action_id"],
        ))
    return candidates


def maybe_apply_transfers(
    *,
    target_store_id: str,
    fleet_store_ids: list[str] | None = None,
    max_per_target: int | None = None,
) -> dict[str, Any]:
    """Compute + enqueue transfer candidates for a target
    store.

    Pattern J short-circuits under pytest. Env gate
    ``SHOPAI_AUTO_TRANSFER=1`` required for the enqueue.

    Returns a summary dict suitable for inclusion in the
    cycle summary's ``transfer`` block:
      {
        "checked": bool,
        "target_store_id": str,
        "candidates_found": int,
        "applied": int,
        "applied_transfers": [{...}],
        "candidates_preview": [{...}],
      }
    """
    out: dict[str, Any] = {
        "checked": True,
        "target_store_id": target_store_id,
        "enabled": is_enabled(),
        "candidates_found": 0,
        "applied": 0,
        "applied_transfers": [],
        "candidates_preview": [],
    }

    candidates = find_transfer_candidates(
        target_store_id=target_store_id,
        fleet_store_ids=fleet_store_ids,
        max_candidates=max_per_target,
    )
    out["candidates_found"] = len(candidates)
    out["candidates_preview"] = [
        {
            "engine": c.engine,
            "action_type": c.action_type,
            "capability": c.capability,
            "source_store_id": c.source_store_id,
            "positive_outcomes": c.positive_outcomes,
            "total_revenue": c.total_revenue,
        }
        for c in candidates
    ]

    if not candidates:
        return out
    if _is_test_environment():
        return out
    if not is_enabled():
        return out

    try:
        from core.approval.queue import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cycle_transfer: enqueue setup raised: %s",
            exc,
        )
        return out

    applied: list[dict[str, Any]] = []
    for c in candidates:
        narrative = (
            f"Auto-transfer: {c.engine}/{c.action_type} "
            f"from {c.source_store_id} -> "
            f"{target_store_id}. "
            f"Source had "
            f"{c.source_success_count} successful run(s), "
            f"+{c.positive_outcomes}/"
            f"-{c.negative_outcomes} outcomes."
        )
        try:
            action = queue.enqueue(
                engine=c.engine,
                action_type=c.action_type,
                capability=c.capability,
                params=dict(c.sample_params or {}),
                narrative=narrative,
                store_id=target_store_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cycle_transfer: enqueue raised: %s",
                exc,
            )
            continue
        applied.append({
            "action_id": getattr(action, "id", None),
            "engine": c.engine,
            "action_type": c.action_type,
            "capability": c.capability,
            "source_store_id": c.source_store_id,
            "positive_outcomes": c.positive_outcomes,
            "total_revenue": c.total_revenue,
        })

        # Audit log the applied transfer.
        try:
            from core.autonomous import (
                transfer_history as _th,
            )
            _th.record_transfer(
                target_store_id=target_store_id,
                source_store_id=c.source_store_id,
                engine=c.engine,
                action_type=c.action_type,
                capability=c.capability,
                action_id=getattr(action, "id", None),
                metrics={
                    "positive_outcomes": c.positive_outcomes,
                    "total_revenue": c.total_revenue,
                    "source_success_count": (
                        c.source_success_count
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cycle_transfer: history record "
                "raised: %s", exc,
            )

    out["applied"] = len(applied)
    out["applied_transfers"] = applied
    return out


def config_summary() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "max_per_store": max_per_store(),
        "min_outcomes": min_outcomes(),
    }
