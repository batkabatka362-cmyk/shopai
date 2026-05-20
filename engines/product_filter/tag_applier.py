"""Product Filter Engine -- per-product rejection-reason tag applier.

The engine evaluates each candidate against four filter stages
(margin / legal / shipping / brand) and emits two lists:
``accepted_products`` and ``rejected_products``. Each rejected
entry carries ``rejection_stage`` (margin_filter /
legal_filter / shipping_filter / brand_filter) and a
``rejection_reason``. Pre-fix the rejection signal landed in
engine output only -- the merchant had to manually translate
"this product failed our margin floor at $14.50 / 12.3%" into
a Shopify admin worklist.

This applier closes the loop. For each rejected product, push
``shopai-filter-rejected-{reason}`` on the product via
``SHOPIFY_ADD_TAGS`` (additive -- existing tags preserved).
``reason`` is one of ``margin`` / ``legal`` / ``shipping`` /
``brand`` (the filter stage's slug). Merchants then save admin
searches / smart collections to drive a "products that didn't
clear our filter, by reason" worklist; downstream engines
(catalog / storefront / paid_ads) suppress these from
recommendation slots or scope ad spend away from them.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_filter_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately per rejection.
  data.apply_filter_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The rejected entry has no product id
  * The rejection_stage isn't one of the four recognised
    stages (defensive guard for hand-built test data)
  * Duplicate product_ids deduped (first-rejection wins --
    later stages don't run on already-rejected items but be
    defensive)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_filter.tag_applier")


_TAG_PREFIX = "shopai-filter-rejected-"

# Maps the filter stage emitted by the engine to a short
# Shopify-safe slug. New stages added to the engine that don't
# appear here are silently skipped (defensive — better than
# pushing a malformed tag and confusing merchants).
_STAGE_TO_REASON: dict[str, str] = {
    "margin_filter": "margin",
    "legal_filter": "legal",
    "shipping_filter": "shipping",
    "brand_filter": "brand",
}


def apply_filter_tags(
    rejected_products: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-filter-rejected-{reason}`` on each rejection.

    Returns per-product list with
    ``{product_id, rejection_stage, reason, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(rejected_products)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    rejected_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter rejections to actionable per-product rows."""
    if not isinstance(rejected_products, list):
        return []
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in rejected_products:
        if not isinstance(entry, dict):
            continue
        # The engine uses ``id`` (and "unknown" as default
        # when a candidate has no id). Filter both.
        product_id = str(entry.get("id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        if product_id in seen:
            continue
        stage = str(entry.get("rejection_stage") or "").strip()
        reason = _STAGE_TO_REASON.get(stage)
        if reason is None:
            continue
        seen.add(product_id)
        rejection_reason = str(
            entry.get("rejection_reason") or "",
        ).strip()
        proposals.append({
            "product_id": product_id,
            "rejection_stage": stage,
            "reason": reason,
            "rejection_reason": rejection_reason,
            "tag": f"{_TAG_PREFIX}{reason}",
        })
    return proposals


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
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
                "product_filter tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
            "reason": p["reason"],
            "rejection_stage": p["rejection_stage"],
            "rejection_reason": p["rejection_reason"],
        }
        reason_part = (
            f": {p['rejection_reason']}"
            if p["rejection_reason"]
            else ""
        )
        narrative = (
            f"product_filter: tag product {p['product_id']} "
            f"as rejected ({p['reason']}{reason_part}) -> "
            f"{p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="product_filter",
                action_type="tag_filter_rejected",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_filter enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "rejection_stage": p["rejection_stage"],
                "reason": p["reason"],
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
            "rejection_stage": p["rejection_stage"],
            "reason": p["reason"],
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
            engine="product_filter",
            action_type="tag_filter_rejected",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_filter record_writeback raised for %s: %s",
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
