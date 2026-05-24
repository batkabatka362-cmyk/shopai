"""Stock Prediction Engine -- restock-recommended tag applier.

Bridges the engine's prediction list into Shopify product
updates. Each product with restock_qty > 0 (engine recommends
restocking now) gets tagged so operators can filter the admin
catalog by SKUs that need restocking.

Tag written:
  * ``stock:restock_recommended``

Products with restock_qty == 0 silently skipped. Same merge
semantics + Pattern Z recording as other Phase 7 tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.stock_prediction.tag_applier")


_RESTOCK_TAG = "stock:restock_recommended"


def apply_restock_tags(
    predictions: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products needing restock via SHOPIFY_UPDATE_PRODUCT.

    Args:
        predictions: From ``StockPredictionEngine.run()``'s
            ``data.predictions``. Each carries ``product_id``
            + ``restock_qty``.
        products: Input list -- merge base.

    Returns:
        Per-restock-product results dict.
    """
    if not isinstance(predictions, list) or not predictions:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(p), "router_unavailable")
            for p in predictions
            if isinstance(p, dict)
            and _product_id(p)
            and _needs_restock(p)
        ]

    results: list[dict[str, Any]] = []
    for pred in predictions:
        if not isinstance(pred, dict):
            continue
        pid = _product_id(pred)
        if not pid or not _needs_restock(pred):
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, [_RESTOCK_TAG])

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "restock_qty": int(pred.get("restock_qty", 0) or 0),
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_restock_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="stock_prediction",
                action_type="apply_restock_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_restock_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="stock_prediction",
                action_type="apply_restock_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="stock_prediction",
            action_type="apply_restock_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "error": None,
        })

    return results


def _needs_restock(pred: dict[str, Any]) -> bool:
    try:
        qty = int(pred.get("restock_qty", 0) or 0)
    except (TypeError, ValueError):
        return False
    return qty > 0


# ── Helpers ───────────────────────────────────────────────────


def _product_id(item: dict[str, Any]) -> str:
    pid = item.get("product_id") or item.get("id") or ""
    return str(pid).strip()


def _build_existing_tags_map(
    products: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not isinstance(products, list):
        return out
    for product in products:
        if not isinstance(product, dict):
            continue
        pid = str(
            product.get("product_id")
            or product.get("id") or "",
        ).strip()
        if not pid:
            continue
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, list):
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


def _skip_result(pid: str, error: str) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [], "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tag_applier capability lookup raised: %s", exc,
        )
        return None
