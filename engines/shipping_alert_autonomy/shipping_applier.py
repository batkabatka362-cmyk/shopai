"""Autonomous shipping_alert tagging (Wave 759).

New autonomy domain scaffolded via shopai autonomy-init.
Tags entities with curated flags via SHOPIFY_TAG_ORDER.

## Safety gates

  1. action='tag_shipping' (engine-approved)
  2. order_id present + tag string non-empty
  3. is_paused() False
  4. tag matches curated taxonomy (anti-typo gate)
  5. per-cycle cap (SHOPAI_SHIPPING_ALERT_MAX_PER_RUN,
     default 250)
  6. router + capability resolution

## Opt-in

``data.apply_shipping_alert=True``. Default OFF.
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.shipping_alert_autonomy.shipping_log import (
    ShippingAlertEvent,
    record_shipping_event,
)
from engines.shipping_alert_autonomy.shipping_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.shipping_alert_autonomy.applier",
)

_ENGINE = "shipping_alert"
_ACTION_TYPE = "apply_shipping_alert_tag"
_WRITEBACK_RISK = "additive"

# Curated taxonomy (anti-typo gate)
_VALID_TAGS: frozenset[str] = frozenset({
    "shopai-shipping-in-transit",
    "shopai-shipping-delayed",
    "shopai-shipping-refused",
    "shopai-shipping-lost",
    "shopai-shipping-delivered",
})


def _max_per_run() -> int:
    raw = os.environ.get(
        "SHOPAI_SHIPPING_ALERT_MAX_PER_RUN",
        "250",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 250


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
            Capability, "SHOPIFY_TAG_ORDER", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    order_id: str,
    store_id: str,
    action: str,
    tag: str,
    signal_source: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_TAG_ORDER",
            params={
                "order_id": order_id,
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
        record_shipping_event(ShippingAlertEvent(
            order_id=order_id,
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


def apply_shipping_alert(
    rows: list[dict[str, Any]],
    *,
    max_per_run: int | None = None,
) -> list[dict[str, Any]]:
    """Tag entities with quality / outreach / etc. flags."""
    if not isinstance(rows, list) or not rows:
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
    for row in rows:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("order_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        tag = str(row.get("tag", "") or "")
        signal = str(row.get("signal_source", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "shipping_alert auto-pause flag set"
        elif action != "tag_shipping":
            status_label = "not_actionable"
        elif not eid or not tag:
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
                    {"order_id": eid, "tags": [tag]},
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
            order_id=eid,
            store_id=sid,
            action=action,
            tag=tag,
            signal_source=signal,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "order_id": eid,
            "tag": tag,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
