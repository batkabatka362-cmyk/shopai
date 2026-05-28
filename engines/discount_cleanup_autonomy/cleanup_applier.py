"""Autonomous discount code deactivation (Wave 157).

Operator pain: discount codes accumulate over time. Recovery
codes minted per-customer (Wave 6+ cart_recovery,
browse_recovery, churn_prediction, etc.), one-off promo codes,
expired campaigns -- the store admin can list 1000+ codes
within months.

Wave 157 closes the loop: autonomous
``SHOPIFY_DEACTIVATE_CODE_DISCOUNT`` for codes the caller
identifies as cleanup-ready.

## Safety gates

  1. action='deactivate'
  2. discount_id present + code non-empty
  3. is_paused() False
  4. age_days >= SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS
     (default 30 -- don't deactivate codes that JUST launched)
  5. usage_count met or older than max_age
  6. SHOPAI_DISCOUNT_CLEANUP_MAX_PER_RUN ceiling (default 50)

## Opt-in

``data.apply_discount_cleanup=True`` at caller level.
Same Phase 6/7 pattern as refund/budget/fulfillment/inventory.

## Skip taxonomy

  paused / not_actionable / missing_ids / too_young /
  exceeds_per_run_cap / router_unavailable / adapter_failed
  / recorded
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.discount_cleanup_autonomy.cleanup_log import (
    DiscountCleanupEvent,
    record_cleanup_event,
)
from engines.discount_cleanup_autonomy.cleanup_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.discount_cleanup_autonomy.applier",
)

_ENGINE = "discount_cleanup"
_ACTION_TYPE = "apply_discount_deactivate"


def _min_age_days() -> int:
    raw = os.environ.get(
        "SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS", "30",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 30


def _max_per_run() -> int:
    raw = os.environ.get(
        "SHOPAI_DISCOUNT_CLEANUP_MAX_PER_RUN", "50",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 50


def _get_router() -> Any | None:
    try:
        from core.adapters.router import get_router
        return get_router()
    except Exception:  # noqa: BLE001
        return None


def _capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return getattr(
            Capability,
            "SHOPIFY_DEACTIVATE_CODE_DISCOUNT",
            None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    discount_id: str,
    code: str,
    store_id: str,
    reason: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + Wave 154 log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_DEACTIVATE_CODE_DISCOUNT",
            params={
                "discount_id": discount_id,
                "code": code,
                "store_id": store_id,
                "reason": reason,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_cleanup_event(DiscountCleanupEvent(
            discount_id=discount_id,
            code=code,
            store_id=store_id,
            reason=reason,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_discount_cleanup(
    candidates: list[dict[str, Any]],
    *,
    min_age_days: int | None = None,
    max_per_run: int | None = None,
) -> list[dict[str, Any]]:
    """Deactivate code discounts behind safety gates.

    Args:
        candidates: list of {discount_id, code, store_id,
                    action, age_days, reason} dicts.
        min_age_days: Override SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS.
        max_per_run: Override SHOPAI_DISCOUNT_CLEANUP_MAX_PER_RUN.

    Returns:
        Per-candidate list with {discount_id, code, applied,
        status, error}.
    """
    if not isinstance(candidates, list) or not candidates:
        return []

    cap_age = (
        min_age_days if min_age_days is not None
        else _min_age_days()
    )
    cap_run = (
        max_per_run if max_per_run is not None
        else _max_per_run()
    )
    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    deactivated_so_far = 0
    for row in candidates:
        if not isinstance(row, dict):
            continue
        did = str(row.get("discount_id", "") or "")
        code = str(row.get("code", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        reason = str(row.get("reason", "") or "")
        try:
            age_days = int(row.get("age_days", 0) or 0)
        except (TypeError, ValueError):
            age_days = 0
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "discount cleanup auto-pause flag set"
        elif action != "deactivate":
            status_label = "not_actionable"
        elif not did or not code:
            status_label = "missing_ids"
        elif age_days < cap_age:
            status_label = "too_young"
            error = (
                f"age_days={age_days} < min={cap_age}"
            )
        elif deactivated_so_far >= cap_run:
            status_label = "exceeds_per_run_cap"
            error = (
                f"per-run cap reached: {cap_run}"
            )
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap, {"discount_id": did},
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                    deactivated_so_far += 1
                else:
                    status_label = "adapter_failed"
                    err_obj = getattr(
                        res, "error", "adapter_failed",
                    )
                    error = (
                        str(err_obj) if err_obj is not None
                        else "adapter_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                status_label = "adapter_failed"
                error = str(exc)

        _record(
            discount_id=did,
            code=code,
            store_id=sid,
            reason=reason,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "discount_id": did,
            "code": code,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
