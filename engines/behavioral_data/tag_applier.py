"""Behavioral Data Engine -- engagement tag applier.

Bridges the engine's ``top_products`` (click summaries) list into
Shopify product updates. Products are tagged based on their
traffic + CTR signals so merchandising surfaces can spot both
WINNERS (high views + high CTR) and OPTIMIZATION CANDIDATES
(high views + low CTR -- creative needs improvement).

Tag composition (requires ``views >= 100`` for either tag):
  * ``engagement:hot``               -- views >= 100 AND ctr >= 0.10
  * ``engagement:high_view_low_ctr`` -- views >= 100 AND ctr < 0.05

The two tags are mutually exclusive (a product can't be both
"hot" AND "low_ctr"). Products in the 5-10% CTR mid-band carry
neither -- they're "normal" and don't need attention.

Low-traffic products (views < 100) silently skipped -- not
enough signal to act on; CTR is noisy with small samples.

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.behavioral_data.tag_applier")


_HOT_TAG = "engagement:hot"
_LOW_CTR_TAG = "engagement:high_view_low_ctr"
_MIN_VIEWS = 100
_HOT_CTR_THRESHOLD = 0.10
_LOW_CTR_THRESHOLD = 0.05


def apply_engagement_tags(
    top_products: list[dict[str, Any]],
    product_views: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Tag products with engagement signals.

    Args:
        top_products: From ``BehavioralDataEngine.run()``'s
            ``data.top_products``. Each carries ``product_id``,
            ``views``, ``clicks``, ``click_through_rate``.
        product_views: Optional input list (carries existing tags
            via product_views[].tags if available). Merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(top_products, list) or not top_products:
        return []

    existing_by_id = _build_existing_tags_map(product_views)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(
                str(p.get("product_id", "")),
                "router_unavailable",
                views=int(p.get("views", 0) or 0),
                ctr=float(p.get("click_through_rate", 0.0) or 0.0),
            )
            for p in top_products
            if isinstance(p, dict)
            and str(p.get("product_id", "")).strip()
            and _has_signal(p)
        ]

    results: list[dict[str, Any]] = []
    for product in top_products:
        if not isinstance(product, dict):
            continue
        pid = str(product.get("product_id", "")).strip()
        if not pid:
            continue
        views = int(product.get("views", 0) or 0)
        ctr = float(product.get("click_through_rate", 0.0) or 0.0)
        if views < _MIN_VIEWS:
            continue

        tag = _pick_tag(views, ctr)
        if not tag:
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, [tag])

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "views": views, "ctr": ctr,
                "tag": tag, "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "views": views,
            "clicks": int(product.get("clicks", 0) or 0),
            "ctr": ctr,
            "tag": tag,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_engagement_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="behavioral_data",
                action_type="apply_engagement_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "views": views, "ctr": ctr, "tag": tag,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_engagement_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="behavioral_data",
                action_type="apply_engagement_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "views": views, "ctr": ctr, "tag": tag,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="behavioral_data",
            action_type="apply_engagement_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "views": views, "ctr": ctr, "tag": tag,
            "error": None,
        })

    return results


def _has_signal(product: dict[str, Any]) -> bool:
    try:
        views = int(product.get("views", 0) or 0)
        ctr = float(product.get("click_through_rate", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    if views < _MIN_VIEWS:
        return False
    return _pick_tag(views, ctr) != ""


def _pick_tag(views: int, ctr: float) -> str:
    if views < _MIN_VIEWS:
        return ""
    if ctr >= _HOT_CTR_THRESHOLD:
        return _HOT_TAG
    if ctr < _LOW_CTR_THRESHOLD:
        return _LOW_CTR_TAG
    return ""


# -- Helpers ---------------------------------------------------


def _build_existing_tags_map(
    product_views: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Build a tags map from product_views (when caller supplies
    them with tags). Most callers won't; the map is empty and
    the applier writes only the new engagement tag.
    """
    out: dict[str, list[str]] = {}
    if not isinstance(product_views, list):
        return out
    for view in product_views:
        if not isinstance(view, dict):
            continue
        pid = str(view.get("product_id", "")).strip()
        if not pid or pid in out:
            continue
        tags = view.get("tags") or []
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


def _skip_result(
    pid: str, error: str,
    *, views: int = 0, ctr: float = 0.0,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "views": views, "ctr": ctr,
        "tag": "", "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "behavioral_data tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "behavioral_data tag_applier capability lookup raised: %s",
            exc,
        )
        return None
