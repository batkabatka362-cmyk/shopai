"""Autonomous inventory reorder (Wave 135).

The inventory engine identifies SKUs that need restocking
(quantity below safety stock + lead time considerations).
Wave 135 closes the loop with autonomous
``SHOPIFY_SET_INVENTORY_QUANTITIES``.

## Safety gates

  1. action='reorder' or 'restock'
  2. sku + location_id + new_quantity > 0
  3. is_paused() False (Wave 133 flag)
  4. new_quantity within SHOPAI_INVENTORY_MAX_QUANTITY ceiling
     (default 10000 -- prevent typos like 100000)
  5. delta from prior > SHOPAI_INVENTORY_MIN_DELTA (default 1)

## Opt-in

``data.apply_inventory_reorders=True``. Default OFF.
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.inventory_autonomy.inventory_log import (
    InventoryEvent,
    record_inventory_event,
)
from engines.inventory_autonomy.inventory_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger("engines.inventory_autonomy.applier")

_ENGINE = "inventory"
_ACTION_TYPE = "apply_inventory_reorder"
# SHOPIFY_SET_INVENTORY_QUANTITIES overwrites stock counts --
# a state mutation, not entity creation.
_WRITEBACK_RISK = "modification"


def _max_quantity() -> int:
    raw = os.environ.get(
        "SHOPAI_INVENTORY_MAX_QUANTITY", "10000",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 10000


def _min_delta() -> int:
    raw = os.environ.get("SHOPAI_INVENTORY_MIN_DELTA", "1")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


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
            "SHOPIFY_SET_INVENTORY_QUANTITIES",
            None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    sku: str,
    location_id: str,
    store_id: str,
    prior: int,
    new: int,
    reason: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + Wave 132 log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_SET_INVENTORY_QUANTITIES",
            params={
                "sku": sku,
                "location_id": location_id,
                "store_id": store_id,
                "prior_quantity": prior,
                "new_quantity": new,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_inventory_event(InventoryEvent(
            sku=sku,
            location_id=location_id,
            store_id=store_id,
            action="reorder",
            prior_quantity=prior,
            new_quantity=new,
            reason=reason,
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_inventory_reorders(
    reorders: list[dict[str, Any]],
    *,
    max_quantity: int | None = None,
    min_delta: int | None = None,
) -> list[dict[str, Any]]:
    """Apply autonomous SET_INVENTORY_QUANTITIES for each
    engine-approved reorder."""
    if not isinstance(reorders, list) or not reorders:
        return []

    cap_q = (
        max_quantity if max_quantity is not None
        else _max_quantity()
    )
    cap_delta = (
        min_delta if min_delta is not None else _min_delta()
    )
    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    for row in reorders:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("sku", "") or "")
        lid = str(row.get("location_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        try:
            prior = int(row.get("prior_quantity", 0) or 0)
        except (TypeError, ValueError):
            prior = 0
        try:
            new_q = int(row.get("new_quantity", 0) or 0)
        except (TypeError, ValueError):
            new_q = 0
        reason = str(row.get("reason", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "inventory auto-pause flag set"
        elif action not in ("reorder", "restock"):
            status_label = "not_actionable"
        elif not sku or not lid or new_q <= 0:
            status_label = "missing_or_invalid_ids"
        elif new_q > cap_q:
            status_label = "exceeds_max_quantity"
            error = f"new_quantity={new_q} > cap={cap_q}"
        elif abs(new_q - prior) < cap_delta:
            status_label = "delta_too_small"
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                res = router.execute(
                    cap,
                    {
                        "sku": sku,
                        "location_id": lid,
                        "quantity": new_q,
                    },
                )
                if getattr(res, "ok", False):
                    applied = True
                    status_label = "recorded"
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
            sku=sku, location_id=lid, store_id=sid,
            prior=prior, new=new_q, reason=reason,
            applied=applied, status=status_label, error=error,
        )
        out.append({
            "sku": sku,
            "location_id": lid,
            "applied": applied,
            "prior_quantity": prior,
            "new_quantity": new_q,
            "status": status_label,
            "error": error,
        })
    return out
