"""Price Elasticity Engine -- per-product elasticity tag applier.

The engine calculates per-product price elasticity (how
sensitive demand is to price changes). It emits
``elasticity`` rows with ``coefficient`` (absolute value;
> 1.0 = elastic), ``optimal_price``, ``expected_revenue``,
and ``is_elastic`` bool. Pre-fix the signal landed in engine
output only -- merchants had to manually translate "this
product has inelastic demand at 0.4 coefficient" into a
Shopify segment.

This applier closes the loop. By default, tag INELASTIC
products with ``shopai-price-inelastic`` -- these are the
SKUs where price increases barely move demand, so they're
safe candidates for upward repricing / premium positioning.
Tag ELASTIC products with ``shopai-price-elastic`` only when
explicitly opted in -- these need careful price management,
which most operators handle case-by-case rather than via a
"warning" worklist.

Merchants then save admin searches to drive a "safe to
reprice upward" worklist; downstream engines (dynamic_pricing
/ paid_ads) gate margin-improvement plays on the inelastic
tag to avoid demand cliffs.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_elasticity_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_elasticity_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id (or "unknown" literal)
  * Coefficient missing / non-numeric (signal too weak)
  * is_elastic=True and include_elastic=False (default)
  * Duplicate product_ids deduped (last-seen wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.price_elasticity.tag_applier")


_INELASTIC_TAG = "shopai-price-inelastic"
_ELASTIC_TAG = "shopai-price-elastic"


def apply_elasticity_tags(
    elasticity: list[dict[str, Any]],
    *,
    include_elastic: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-price-{inelastic|elastic}`` on each product.

    Each entry in ``elasticity`` is
    ``{product_id, coefficient, optimal_price,
    expected_revenue, is_elastic}``. Returns per-product list
    with ``{product_id, coefficient, bucket, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(
        elasticity, include_elastic=include_elastic,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    elasticity: list[dict[str, Any]],
    *,
    include_elastic: bool,
) -> list[dict[str, Any]]:
    """Filter elasticity rows to actionable per-product tags."""
    if not isinstance(elasticity, list):
        return []
    seen: dict[str, dict[str, Any]] = {}
    for entry in elasticity:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        try:
            coefficient = float(entry.get("coefficient", 0.0))
        except (TypeError, ValueError):
            continue
        is_elastic = bool(entry.get("is_elastic", False))

        if is_elastic:
            if not include_elastic:
                continue
            bucket = "elastic"
            tag = _ELASTIC_TAG
        else:
            bucket = "inelastic"
            tag = _INELASTIC_TAG

        try:
            optimal_price = float(entry.get("optimal_price", 0.0))
        except (TypeError, ValueError):
            optimal_price = 0.0

        # Last-seen-wins dedup: a product shouldn't appear twice
        # but be defensive against hand-built data.
        seen[product_id] = {
            "product_id": product_id,
            "coefficient": round(coefficient, 4),
            "optimal_price": round(optimal_price, 2),
            "bucket": bucket,
            "tag": tag,
        }
    return list(seen.values())


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
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
                "price_elasticity tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
            "bucket": p["bucket"],
            "coefficient": p["coefficient"],
            "optimal_price": p["optimal_price"],
        }
        narrative = (
            f"price_elasticity: tag product {p['product_id']} "
            f"as {p['bucket']} (coef={p['coefficient']}) -> "
            f"{p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="price_elasticity",
                action_type="tag_price_elasticity",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "price_elasticity enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "coefficient": p["coefficient"],
                "bucket": p["bucket"],
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
            "coefficient": p["coefficient"],
            "bucket": p["bucket"],
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
            engine="price_elasticity",
            action_type="tag_price_elasticity",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "price_elasticity record_writeback raised for %s: %s",
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
