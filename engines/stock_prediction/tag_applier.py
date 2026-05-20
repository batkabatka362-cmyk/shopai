"""Stock Prediction Engine -- per-product stock-out-risk tag applier.

The engine predicts 30/90-day demand per product and classifies
each one's restock urgency as ``critical`` (out / overdue),
``high`` (≤7 days), ``medium`` (≤14 days), or ``low``. Pre-fix
the urgency signal landed in the restock_recommender's
intermediate output -- the merchant couldn't pull a "products
about to stock out" segment without manually crunching the
predictions.

This applier closes the loop. For high-urgency products, push
``shopai-stock-{urgency}`` on the product via
``SHOPIFY_ADD_TAGS`` (additive -- existing tags preserved).
``urgency`` is ``critical`` or ``high``. Merchants then save
admin searches to drive a "products needing restock" worklist;
downstream engines (catalog / storefront / paid_ads) can
suppress these from featured slots or pause ad spend on
products that will stock out before the ads ROI.

Only ``critical`` is tagged by default -- ``high`` is opt-in
via ``include_high=True``. ``medium`` / ``low`` are noise
for the operational worklist.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_stock_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_stock_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id
  * The urgency isn't ``critical`` (and not ``high`` when
    include_high=True)
  * Duplicate product_ids deduped (most-urgent wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.stock_prediction.tag_applier")


_TAG_PREFIX = "shopai-stock-"
_CRITICAL = "critical"
_HIGH = "high"
# Urgency level → numeric priority for "most-urgent wins" dedup
_URGENCY_RANK = {
    _CRITICAL: 4,
    _HIGH: 3,
    "medium": 2,
    "low": 1,
}


def apply_stock_tags(
    predictions: list[dict[str, Any]],
    *,
    include_high: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-stock-{urgency}`` on each at-risk product.

    Each entry in ``predictions`` is
    ``{product_id, urgency, restock_date, restock_qty,
    predicted_demand_30d, predicted_demand_90d}``. Returns
    per-product list with
    ``{product_id, urgency, tag, applied, error}``. When
    ``require_approval=True`` (default), ``applied`` is False
    for queue-only entries.
    """
    proposals = _build_proposals(
        predictions, include_high=include_high,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    predictions: list[dict[str, Any]],
    *,
    include_high: bool,
) -> list[dict[str, Any]]:
    """Filter predictions to actionable per-product rows.

    Most-urgent wins per product: if the same product_id
    appears twice (rare, but possible), keep the higher
    urgency level.
    """
    if not isinstance(predictions, list):
        return []
    allowed = {_CRITICAL}
    if include_high:
        allowed = {_CRITICAL, _HIGH}

    worst: dict[str, dict[str, Any]] = {}
    for entry in predictions:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id:
            continue
        urgency = str(
            entry.get("urgency") or "",
        ).strip().lower()
        if urgency not in allowed:
            continue
        try:
            qty = int(entry.get("restock_qty", 0) or 0)
        except (TypeError, ValueError):
            qty = 0
        restock_date = str(entry.get("restock_date") or "").strip()

        existing = worst.get(product_id)
        if existing is None or (
            _URGENCY_RANK.get(urgency, 0)
            > _URGENCY_RANK.get(existing["urgency"], 0)
        ):
            worst[product_id] = {
                "product_id": product_id,
                "urgency": urgency,
                "restock_date": restock_date,
                "restock_qty": qty,
                "tag": f"{_TAG_PREFIX}{urgency}",
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
                "urgency": p["urgency"],
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
                "stock_prediction tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "urgency": p["urgency"],
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
                "urgency": p["urgency"],
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
                "urgency": p["urgency"],
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
                "urgency": p["urgency"],
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
            "urgency": p["urgency"],
            "restock_date": p["restock_date"],
            "restock_qty": p["restock_qty"],
        }
        date_part = (
            f" by {p['restock_date']}" if p["restock_date"] else ""
        )
        narrative = (
            f"stock_prediction: tag product {p['product_id']} "
            f"as stock-{p['urgency']}{date_part} (qty "
            f"{p['restock_qty']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="stock_prediction",
                action_type="tag_stock_at_risk",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "stock_prediction enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "urgency": p["urgency"],
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
            "urgency": p["urgency"],
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
            engine="stock_prediction",
            action_type="tag_stock_at_risk",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "stock_prediction record_writeback raised for %s: %s",
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
