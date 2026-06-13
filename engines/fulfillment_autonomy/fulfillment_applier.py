"""Autonomous fulfillment router (Wave 129).

The order_management engine produces routing decisions (which
location should fulfill each pending order). Pre-Wave-129
those decisions were advisory. Wave 129 closes the loop:
autonomous ``SHOPIFY_CREATE_FULFILLMENT`` for engine-approved
routes.

## Safety gates

  1. action='route' (engine-approved; not 'hold')
  2. order_id + location_id both present
  3. fulfillment_state.is_paused() False (Wave 127 flag)
  4. router + capability resolution

## Opt-in

``data.apply_fulfillment_routes=True``. Default OFF.

## Skip taxonomy

  paused / not_actionable / missing_ids / router_unavailable
  / adapter_failed / recorded
"""
from __future__ import annotations

from typing import Any

from engines._writeback_recorder import record_writeback
from engines.fulfillment_autonomy.fulfillment_log import (
    FulfillmentEvent,
    record_fulfillment_event,
)
from engines.fulfillment_autonomy.fulfillment_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger("engines.fulfillment_autonomy.router")

_ENGINE = "order_management"
_ACTION_TYPE = "apply_fulfillment_route"


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
            Capability, "SHOPIFY_CREATE_FULFILLMENT", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    order_id: str,
    location_id: str,
    store_id: str,
    fulfillment_id: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + Wave 126 log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_CREATE_FULFILLMENT",
            params={
                "order_id": order_id,
                "location_id": location_id,
                "store_id": store_id,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_fulfillment_event(FulfillmentEvent(
            order_id=order_id,
            location_id=location_id,
            store_id=store_id,
            action="route",
            fulfillment_id=fulfillment_id,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_fulfillment_routes(
    routes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Issue SHOPIFY_CREATE_FULFILLMENT for each engine-approved
    route.

    Args:
        routes: list of {order_id, location_id, store_id,
                action} dicts (typically engine output).

    Returns:
        Per-route list with {order_id, location_id, applied,
        status, error}.
    """
    if not isinstance(routes, list) or not routes:
        return []

    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    for row in routes:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("order_id", "") or "")
        lid = str(row.get("location_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        applied = False
        status_label = ""
        error: str | None = None
        fulfillment_id = ""

        if paused:
            status_label = "paused"
            error = "fulfillment auto-pause flag set"
        elif action != "route":
            status_label = "not_actionable"
        elif not oid or not lid:
            status_label = "missing_ids"
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {
                        "order_id": oid,
                        "location_id": lid,
                    },
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
                    data = getattr(res, "data", None) or {}
                    fulfillment_id = str(
                        data.get("fulfillment_id", "")
                        or data.get("id", ""),
                    )
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
            order_id=oid,
            location_id=lid,
            store_id=sid,
            fulfillment_id=fulfillment_id,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "order_id": oid,
            "location_id": lid,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
