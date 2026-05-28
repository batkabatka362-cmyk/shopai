"""Autonomous product SEO metadata update (Wave 198).

Updates products' meta_description / meta_title via
SHOPIFY_UPDATE_PRODUCT. Caller supplies the generated text
(typically from content_generation engine); the applier
gates + writes.

## Safety gates

  1. action='update_seo'
  2. product_id + field name present + new_value non-empty
  3. field is one of {meta_description, meta_title}
  4. is_paused() False
  5. new_value length within SHOPAI_PRODUCT_SEO_MAX_LENGTH
     (default 320 chars -- Google snippet ceiling)
  6. router + capability resolution
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.product_seo_autonomy.seo_log import (
    ProductSEOEvent,
    record_seo_event,
)
from engines.product_seo_autonomy.seo_state import is_paused
from utils.logger import get_logger

logger = get_logger(
    "engines.product_seo_autonomy.applier",
)

_ENGINE = "product_seo"
_ACTION_TYPE = "apply_product_seo_update"

_VALID_FIELDS: frozenset[str] = frozenset({
    "meta_description",
    "meta_title",
})


def _max_length() -> int:
    raw = os.environ.get(
        "SHOPAI_PRODUCT_SEO_MAX_LENGTH", "320",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 320


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
            Capability, "SHOPIFY_UPDATE_PRODUCT", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    product_id: str,
    store_id: str,
    field: str,
    new_value: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_UPDATE_PRODUCT",
            params={
                "product_id": product_id,
                "store_id": store_id,
                "field": field,
            },
            success=applied,
            error=error,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        record_seo_event(ProductSEOEvent(
            product_id=product_id,
            store_id=store_id,
            seo_field=field,
            new_value_preview=new_value[:80],
            applied=applied,
            status=status,
            error=error or "",
        ))
    except Exception:  # noqa: BLE001
        pass


def apply_seo_updates(
    updates: list[dict[str, Any]],
    *,
    max_length: int | None = None,
) -> list[dict[str, Any]]:
    """Apply SEO field updates per product."""
    if not isinstance(updates, list) or not updates:
        return []

    cap_len = (
        max_length if max_length is not None else _max_length()
    )
    paused = is_paused()
    router = _get_router() if not paused else None
    cap = _capability() if not paused else None

    out: list[dict[str, Any]] = []
    for row in updates:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("product_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        field = str(row.get("field", "") or "").lower()
        new_value = str(row.get("new_value", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "product SEO auto-pause flag set"
        elif action != "update_seo":
            status_label = "not_actionable"
        elif not pid or not new_value or not field:
            status_label = "missing_ids"
        elif field not in _VALID_FIELDS:
            status_label = "invalid_field"
            error = (
                f"field={field!r} not in "
                f"{sorted(_VALID_FIELDS)}"
            )
        elif len(new_value) > cap_len:
            status_label = "exceeds_max_length"
            error = (
                f"len={len(new_value)} > cap={cap_len}"
            )
        elif router is None or cap is None:
            status_label = "router_unavailable"
        else:
            try:
                # Map our field name to Shopify's seo subfield
                seo_payload = (
                    {"seo": {"description": new_value}}
                    if field == "meta_description"
                    else {"seo": {"title": new_value}}
                )
                res = router.execute(
                    cap,
                    {
                        "product_id": pid,
                        **seo_payload,
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
            product_id=pid,
            store_id=sid,
            field=field,
            new_value=new_value,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "product_id": pid,
            "field": field,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
