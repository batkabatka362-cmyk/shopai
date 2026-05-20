"""Order Quality Engine -- per-product high-defect-rate tag applier.

The engine tracks order defects and rolls them up into
per-supplier and per-product defect rates. Pre-fix the signal
landed in engine output only -- merchants had to manually
translate "this product hits a 12% defect rate" into a
Shopify admin worklist.

This applier closes the loop. For products with a defect rate
at or above ``min_defect_rate`` (default 0.10 = 10%), push
``shopai-defect-high-rate`` on the product via
``SHOPIFY_ADD_TAGS`` (additive -- existing tags preserved).
Supplier-rollup entries are intentionally SKIPPED -- the
applier tags PRODUCTS (Shopify entities), not arbitrary
supplier strings.

Merchants then save admin searches to drive a "QA hot list"
worklist; downstream engines (catalog / storefront /
paid_ads) can suppress these from featured slots, pause ads,
or trigger supplier-review workflows before promoting.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_quality_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_quality_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The ``min_defect_rate`` threshold
(default 0.10) lives in input data so callers can tune signal
strength without changing the engine output shape.

Skipped (no API call / no queue entry) when:
  * The entry isn't ``entity_type=product`` (supplier rollups
    skipped)
  * The entity is blank
  * ``defect_rate`` falls below ``min_defect_rate``
  * Duplicate entities deduped (highest-rate wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.order_quality.tag_applier")


_TAG = "shopai-defect-high-rate"
_DEFAULT_MIN_DEFECT_RATE = 0.10


def apply_quality_tags(
    defect_rates: list[dict[str, Any]],
    *,
    min_defect_rate: float = _DEFAULT_MIN_DEFECT_RATE,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-defect-high-rate`` on each defective product.

    Each entry in ``defect_rates`` is
    ``{entity, entity_type, total_orders, defect_count,
    defect_rate}``. Returns per-product list with
    ``{product_id, defect_rate, defect_count, total_orders,
    tag, applied, error}``. When ``require_approval=True``
    (default), ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(
        defect_rates, min_defect_rate=min_defect_rate,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    defect_rates: list[dict[str, Any]],
    *,
    min_defect_rate: float,
) -> list[dict[str, Any]]:
    """Filter defect rates to actionable per-product rows."""
    if not isinstance(defect_rates, list):
        return []
    threshold = max(0.0, float(min_defect_rate or 0.0))

    worst: dict[str, dict[str, Any]] = {}
    for entry in defect_rates:
        if not isinstance(entry, dict):
            continue
        # Only PRODUCT rollups become Shopify tags.
        entity_type = str(
            entry.get("entity_type") or "",
        ).strip().lower()
        if entity_type != "product":
            continue
        product_id = str(entry.get("entity") or "").strip()
        if not product_id:
            continue
        try:
            defect_rate = float(entry.get("defect_rate", 0.0))
        except (TypeError, ValueError):
            defect_rate = 0.0
        if defect_rate < threshold:
            continue
        try:
            defect_count = int(entry.get("defect_count", 0) or 0)
        except (TypeError, ValueError):
            defect_count = 0
        try:
            total_orders = int(entry.get("total_orders", 0) or 0)
        except (TypeError, ValueError):
            total_orders = 0

        existing = worst.get(product_id)
        if existing is None or defect_rate > existing["defect_rate"]:
            worst[product_id] = {
                "product_id": product_id,
                "defect_rate": round(defect_rate, 4),
                "defect_count": defect_count,
                "total_orders": total_orders,
                "tag": _TAG,
            }
    return list(worst.values())


def _apply_each_direct(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Direct ``SHOPIFY_ADD_TAGS`` per proposal."""
    router = _get_router()
    capability = _get_add_tags_capability()
    if router is None or capability is None:
        return [
            {
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": False,
                "error": "router_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        try:
            result = router.execute(capability, {
                "id": p["product_id"],
                "tags": [p["tag"]],
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "order_quality tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        ok = bool(getattr(result, "ok", False))
        error = getattr(result, "error", None)
        if ok:
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=True,
            )
            results.append({
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": True,
                "error": None,
            })
        else:
            err_str = str(error or "rejected")
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False, error=err_str,
            )
            results.append({
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": False,
                "error": f"adapter_failed: {err_str}",
            })
    return results


def _enqueue_each(
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enqueue each proposal via the approval queue."""
    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("approval queue unavailable: %s", exc)
        return [
            {
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        params = {
            "product_id": p["product_id"],
            "tag": p["tag"],
            "defect_rate": p["defect_rate"],
            "defect_count": p["defect_count"],
            "total_orders": p["total_orders"],
        }
        narrative = (
            f"order_quality: tag product {p['product_id']} as "
            f"high-defect-rate ({p['defect_count']}/{p['total_orders']} "
            f"= {p['defect_rate']:.1%}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="order_quality",
                action_type="tag_defect_high_rate",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "order_quality enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "defect_rate": p["defect_rate"],
                "defect_count": p["defect_count"],
                "total_orders": p["total_orders"],
                "tag": p["tag"],
                "applied": False,
                "error": f"enqueue_raised: {exc}",
            })
            continue

        _record_writeback_safely(
            product_id=p["product_id"],
            tag=p["tag"], success=True,
        )
        results.append({
            "product_id": p["product_id"],
            "defect_rate": p["defect_rate"],
            "defect_count": p["defect_count"],
            "total_orders": p["total_orders"],
            "tag": p["tag"],
            "applied": False,  # queued, not applied yet
            "pending_action_id": action.id,
            "error": None,
        })
    return results


def _record_writeback_safely(
    *,
    product_id: str,
    tag: str,
    success: bool,
    error: str | None = None,
) -> None:
    """Best-effort Phase 8 recording."""
    try:
        record_writeback(
            engine="order_quality",
            action_type="tag_defect_high_rate",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_quality record_writeback raised for %s: %s",
            product_id, exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router unavailable: %s", exc)
        return None


def _get_add_tags_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_ADD_TAGS
    except Exception as exc:  # noqa: BLE001
        logger.debug("capability resolve failed: %s", exc)
        return None
