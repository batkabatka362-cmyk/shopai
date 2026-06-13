"""Autonomous customer outreach tagging (Wave 382).

8th autonomy domain. Tags customers identified as needing
operator outreach via SHOPIFY_TAG_CUSTOMER. Signals come from
upstream engines (churn_prediction, customer_segmentation,
cohort_analysis, nps_engine) that produce per-customer risk
or engagement scores.

Tag taxonomy (curated -- no arbitrary tag strings allowed):

  - shopai-outreach-at-risk          (high churn probability)
  - shopai-outreach-followup-needed  (recent issue / dispute)
  - shopai-outreach-vip-engagement   (high LTV, declining engagement)
  - shopai-outreach-winback          (dormant > N days)
  - shopai-outreach-reviewed         (operator-marked complete)

Operator filters Shopify admin by these tags + downstream
email / SMS flows consume them. Always ADDITIVE -- merging
the new tag with the customer's existing tag set; never
overwrites operator-set tags.

## Safety gates

  1. action='tag_outreach' (engine-approved)
  2. customer_id present + tag string non-empty
  3. is_paused() False
  4. tag matches curated taxonomy (anti-typo gate)
  5. per-cycle cap (SHOPAI_CUSTOMER_OUTREACH_MAX_PER_RUN,
     default 200 -- prevents accidental mass-tag)
  6. router + capability resolution

## Opt-in

``data.apply_customer_outreach=True``. Default OFF.
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.customer_outreach_autonomy.outreach_log import (
    CustomerOutreachEvent,
    record_outreach_event,
)
from engines.customer_outreach_autonomy.outreach_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.customer_outreach_autonomy.applier",
)

_ENGINE = "customer_outreach"
_ACTION_TYPE = "apply_customer_outreach_tag"
_WRITEBACK_RISK = "additive"

# Curated taxonomy (anti-typo gate)
_VALID_TAGS: frozenset[str] = frozenset({
    "shopai-outreach-at-risk",
    "shopai-outreach-followup-needed",
    "shopai-outreach-vip-engagement",
    "shopai-outreach-winback",
    "shopai-outreach-reviewed",
})


def _max_per_run() -> int:
    raw = os.environ.get(
        "SHOPAI_CUSTOMER_OUTREACH_MAX_PER_RUN", "200",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 200


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
            Capability, "SHOPIFY_TAG_CUSTOMER", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    customer_id: str,
    store_id: str,
    action: str,
    tag: str,
    signal_source: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + W379 log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_TAG_CUSTOMER",
            params={
                "customer_id": customer_id,
                "store_id": store_id,
                "tag": tag,
                "signal_source": signal_source,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_outreach_event(CustomerOutreachEvent(
            customer_id=customer_id,
            store_id=store_id,
            action=action,
            tag=tag,
            signal_source=signal_source,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_customer_outreach(
    outreaches: list[dict[str, Any]],
    *,
    max_per_run: int | None = None,
) -> list[dict[str, Any]]:
    """Tag customers needing outreach.

    Args:
        outreaches: list of {customer_id, store_id, action,
                    tag, signal_source} dicts.
        max_per_run: Override the per-cycle cap.

    Returns:
        Per-row list with {customer_id, tag, applied, status,
        error}.
    """
    if not isinstance(outreaches, list) or not outreaches:
        return []

    cap_run = (
        max_per_run if max_per_run is not None
        else _max_per_run()
    )
    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    tagged_so_far = 0
    for row in outreaches:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("customer_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        tag = str(row.get("tag", "") or "")
        signal = str(row.get("signal_source", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "customer outreach auto-pause flag set"
        elif action != "tag_outreach":
            status_label = "not_actionable"
        elif not cid or not tag:
            status_label = "missing_ids"
        elif tag not in _VALID_TAGS:
            status_label = "invalid_tag"
            error = (
                f"tag={tag!r} not in curated taxonomy"
            )
        elif tagged_so_far >= cap_run:
            status_label = "exceeds_per_run_cap"
            error = (
                f"per-run cap reached: {cap_run}"
            )
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {"customer_id": cid, "tags": [tag]},
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                    tagged_so_far += 1
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
            customer_id=cid,
            store_id=sid,
            action=action,
            tag=tag,
            signal_source=signal,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "customer_id": cid,
            "tag": tag,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
