"""Wishlist Engine -- high-demand product tag applier.

Bridges the engine's ``analysis.top_wishlisted`` list into
Shopify product updates. Products wishlisted by multiple
customers get tagged so merchandising surfaces can spot
demand BEFORE it converts to revenue.

Two-tier composition:
  * ``wishlist:high_demand`` -- wishlist_count >= 3
  * ``wishlist:top_tier``    -- wishlist_count >= 10 (also
    gets the high_demand tag)

Single threshold (count < 3) means most stores will only
tag the genuinely demand-signal products, not random
single-wishlist items.

Same merge semantics + Pattern Z recording as the other
Phase 7 product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.wishlist.tag_applier")


_HIGH_DEMAND_TAG = "wishlist:high_demand"
_TOP_TIER_TAG = "wishlist:top_tier"
_HIGH_DEMAND_THRESHOLD = 3
_TOP_TIER_THRESHOLD = 10


def apply_wishlist_tags(
    top_wishlisted: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag highly-wishlisted products via SHOPIFY_UPDATE_PRODUCT.

    Args:
        top_wishlisted: From ``WishlistEngine.run()``'s
            ``data.analysis.top_wishlisted``. Each carries
            ``product_id`` + ``wishlist_count``.
        products: Input list -- merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(top_wishlisted, list) or not top_wishlisted:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(w), "router_unavailable")
            for w in top_wishlisted
            if isinstance(w, dict)
            and _product_id(w)
            and _wishlist_count(w) >= _HIGH_DEMAND_THRESHOLD
        ]

    results: list[dict[str, Any]] = []
    for entry in top_wishlisted:
        if not isinstance(entry, dict):
            continue
        pid = _product_id(entry)
        count = _wishlist_count(entry)
        if not pid or count < _HIGH_DEMAND_THRESHOLD:
            continue

        new_tags = [_HIGH_DEMAND_TAG]
        if count >= _TOP_TIER_THRESHOLD:
            new_tags.append(_TOP_TIER_TAG)

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "wishlist_count": count,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "wishlist_count": count,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_wishlist_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="wishlist",
                action_type="apply_wishlist_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "wishlist_count": count,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_wishlist_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="wishlist",
                action_type="apply_wishlist_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "wishlist_count": count,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="wishlist",
            action_type="apply_wishlist_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "wishlist_count": count,
            "error": None,
        })

    return results


def _wishlist_count(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("wishlist_count", 0) or 0)
    except (TypeError, ValueError):
        return 0


# -- Helpers ---------------------------------------------------


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
        "tags_added": 0, "merged_tags": [],
        "wishlist_count": 0,
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "wishlist tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "wishlist tag_applier capability lookup raised: %s",
            exc,
        )
        return None
