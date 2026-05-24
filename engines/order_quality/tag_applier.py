"""Order Quality Engine -- defect-rate tag applier.

Bridges the engine's ``defect_rates`` list into Shopify product
updates. Products with elevated defect rates (defects per order)
get tagged so QA + merchandising can surface quality issues in
the catalog admin without re-running the engine.

Tag composition:
  * ``quality:high_defect``   -- defect_rate > 0.10
  * ``quality:medium_defect`` -- defect_rate > 0.05 (<= 0.10)

Low-defect products silently skipped.

Distinct from warranty applier:
  * warranty: claims AFTER sale (customer-reported issues)
  * quality:  defects DURING fulfillment (operator-reported)

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.order_quality.tag_applier")


_HIGH_TAG = "quality:high_defect"
_MEDIUM_TAG = "quality:medium_defect"
_HIGH_THRESHOLD = 0.10
_MEDIUM_THRESHOLD = 0.05


def apply_defect_rate_tags(
    defect_rates: list[dict[str, Any]],
    orders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products with elevated defect rates.

    Args:
        defect_rates: From ``OrderQualityEngine.run()``'s
            ``data.defect_rates``. Each carries ``entity``,
            ``entity_type``, ``defect_rate``. Mixed supplier +
            product entries -- applier filters to products only.
        orders: Input list -- pulls existing product tags from
            order line items where available.

    Returns:
        Per-product results dict.
    """
    if not isinstance(defect_rates, list) or not defect_rates:
        return []

    existing_by_id = _build_existing_tags_from_orders(orders)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(
                str(r.get("entity", "")),
                "router_unavailable",
                defect_rate=_defect_rate(r),
            )
            for r in defect_rates
            if isinstance(r, dict)
            and str(r.get("entity_type", "")) == "product"
            and str(r.get("entity", "")).strip()
            and _defect_rate(r) > _MEDIUM_THRESHOLD
        ]

    results: list[dict[str, Any]] = []
    for entry in defect_rates:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("entity_type", "")) != "product":
            continue
        pid = str(entry.get("entity", "")).strip()
        rate = _defect_rate(entry)
        if not pid or rate <= _MEDIUM_THRESHOLD:
            continue

        new_tag = _HIGH_TAG if rate > _HIGH_THRESHOLD else _MEDIUM_TAG

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, [new_tag])

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "defect_rate": rate,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "defect_rate": rate,
            "defect_count": int(entry.get("defect_count", 0) or 0),
            "total_orders": int(entry.get("total_orders", 0) or 0),
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_defect_rate_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="order_quality",
                action_type="apply_defect_rate_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "defect_rate": rate,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_defect_rate_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="order_quality",
                action_type="apply_defect_rate_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "defect_rate": rate,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="order_quality",
            action_type="apply_defect_rate_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "defect_rate": rate,
            "error": None,
        })

    return results


def _defect_rate(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("defect_rate", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# -- Helpers ---------------------------------------------------


def _build_existing_tags_from_orders(
    orders: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Build existing tags map from order line items.

    Orders carry items[].product_id + items[].tags (when the
    SHOPIFY_FETCH_ORDERS adapter includes them). Fallback to
    empty list if not present -- the merge step will just add
    the new defect tag.
    """
    out: dict[str, list[str]] = {}
    if not isinstance(orders, list):
        return out
    for order in orders:
        if not isinstance(order, dict):
            continue
        for item in order.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("product_id", "")).strip()
            if not pid:
                continue
            tags = item.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if isinstance(tags, list) and pid not in out:
                out[pid] = [str(t) for t in tags if t]
    return out


def _merge_tags(
    existing: list[str], new: list[str],
) -> tuple[list[str], int]:
    seen_lower = {t.lower() for t in existing if isinstance(t, str)}
    merged = list(existing)
    added = 0
    for tag in new:
        if not isinstance(tag, str):
            continue
        if tag.lower() in seen_lower:
            continue
        merged.append(tag)
        seen_lower.add(tag.lower())
        added += 1
    return merged, added


def _skip_result(
    pid: str, error: str, *, defect_rate: float = 0.0,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "defect_rate": defect_rate,
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_quality tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_quality tag_applier capability lookup raised: %s",
            exc,
        )
        return None
