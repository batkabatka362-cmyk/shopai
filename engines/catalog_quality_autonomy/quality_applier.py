"""Autonomous catalog quality tagging (Wave 439).

9th autonomy domain. Tags products with quality flags
identified by upstream engines via SHOPIFY_TAG_PRODUCT.

Signals come from:
  - product_validation (image quality, description length)
  - product_optimization (variant gaps, SEO issues)
  - product_research (verdict signals)
  - review_management (negative review surfaces)

Tag taxonomy (curated -- no arbitrary tag strings):

  - shopai-quality-needs-images        (insufficient/missing images)
  - shopai-quality-thin-description    (description below threshold)
  - shopai-quality-no-variants         (single-variant only)
  - shopai-quality-validated           (passed all checks)
  - shopai-quality-flagged-review      (operator-flagged for review)

Always ADDITIVE -- merging the new tag with the product's
existing tag set; never overwrites operator-set tags.

## Safety gates

  1. action='tag_quality' (engine-approved)
  2. product_id present + tag string non-empty
  3. is_paused() False
  4. tag matches curated taxonomy (anti-typo gate)
  5. per-cycle cap (SHOPAI_CATALOG_QUALITY_MAX_PER_RUN,
     default 300 -- prevents accidental mass-tag)
  6. router + capability resolution

## Opt-in

``data.apply_catalog_quality=True``. Default OFF.
"""
from __future__ import annotations

import os
from typing import Any

from engines._writeback_recorder import record_writeback
from engines.catalog_quality_autonomy.quality_log import (
    CatalogQualityEvent,
    record_quality_event,
)
from engines.catalog_quality_autonomy.quality_state import (
    is_paused,
)
from utils.logger import get_logger

logger = get_logger(
    "engines.catalog_quality_autonomy.applier",
)

_ENGINE = "catalog_quality"
_ACTION_TYPE = "apply_catalog_quality_tag"
_WRITEBACK_RISK = "additive"

# Curated taxonomy (anti-typo gate)
_VALID_TAGS: frozenset[str] = frozenset({
    "shopai-quality-needs-images",
    "shopai-quality-thin-description",
    "shopai-quality-no-variants",
    "shopai-quality-validated",
    "shopai-quality-flagged-review",
})


def _max_per_run() -> int:
    raw = os.environ.get(
        "SHOPAI_CATALOG_QUALITY_MAX_PER_RUN", "300",
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 300


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
            Capability, "SHOPIFY_TAG_PRODUCT", None,
        )
    except Exception:  # noqa: BLE001
        return None


def _record(
    *,
    product_id: str,
    store_id: str,
    action: str,
    tag: str,
    signal_source: str,
    applied: bool,
    status: str,
    error: str | None,
) -> None:
    """Dual recording: Pattern Z + W436 log."""
    try:
        record_writeback(
            engine=_ENGINE,
            action_type=_ACTION_TYPE,
            capability="SHOPIFY_TAG_PRODUCT",
            params={
                "product_id": product_id,
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
        record_quality_event(CatalogQualityEvent(
            product_id=product_id,
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


def apply_catalog_quality(
    quality_flags: list[dict[str, Any]],
    *,
    max_per_run: int | None = None,
) -> list[dict[str, Any]]:
    """Tag products with quality flags.

    Args:
        quality_flags: list of {product_id, store_id, action,
                       tag, signal_source} dicts.
        max_per_run: Override the per-cycle cap.

    Returns:
        Per-row list with {product_id, tag, applied, status,
        error}.
    """
    if not isinstance(quality_flags, list) or not quality_flags:
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
    for row in quality_flags:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("product_id", "") or "")
        sid = str(row.get("store_id", "") or "")
        action = str(row.get("action", "") or "").lower()
        tag = str(row.get("tag", "") or "")
        signal = str(row.get("signal_source", "") or "")
        applied = False
        status_label = ""
        error: str | None = None

        if paused:
            status_label = "paused"
            error = "catalog quality auto-pause flag set"
        elif action != "tag_quality":
            status_label = "not_actionable"
        elif not pid or not tag:
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
                    {"product_id": pid, "tags": [tag]},
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
            product_id=pid,
            store_id=sid,
            action=action,
            tag=tag,
            signal_source=signal,
            applied=applied,
            status=status_label,
            error=error,
        )
        out.append({
            "product_id": pid,
            "tag": tag,
            "applied": applied,
            "status": status_label,
            "error": error,
        })
    return out
