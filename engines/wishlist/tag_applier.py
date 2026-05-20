"""Wishlist Engine -- per-product wishlisted-hot tag applier.

The engine ranks products by wishlist count and surfaces the
most-wishlisted ones in ``analysis.top_wishlisted``. Pre-fix
the popularity signal landed in engine output only -- the
merchant had to manually translate "this product is sitting in
500 wishlists" into a Shopify segment / collection that the
storefront / email engine could target.

This applier closes the loop. For each top-wishlisted product
above a minimum-wishlist-count floor, push a tag
``shopai-wishlisted-hot`` via ``SHOPIFY_ADD_TAGS`` (additive --
existing tags preserved). Merchants then save a Shopify admin
search for the tag, build "popular in wishlists" smart
collections, or downstream engines (email_marketing /
back_in_stock) filter on it to drive demand-pull campaigns.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_wishlist_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately per product.
  data.apply_wishlist_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the approval
    queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The ``min_wishlist_count`` threshold
(default 3) lives in input data so callers can tune signal
strength without changing the engine output shape.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id
  * The wishlist_count falls below ``min_wishlist_count``
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.wishlist.tag_applier")


_WISHLIST_TAG = "shopai-wishlisted-hot"
_DEFAULT_MIN_COUNT = 3


def apply_wishlist_tags(
    top_wishlisted: list[dict[str, Any]],
    *,
    min_wishlist_count: int = _DEFAULT_MIN_COUNT,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-wishlisted-hot`` on each hot product.

    Returns per-product list with
    ``{product_id, title, wishlist_count, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(
        top_wishlisted, min_wishlist_count=min_wishlist_count,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    top_wishlisted: list[dict[str, Any]],
    *,
    min_wishlist_count: int,
) -> list[dict[str, Any]]:
    """Filter the engine's top_wishlisted to actionable rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(top_wishlisted, list):
        return proposals
    threshold = max(1, int(min_wishlist_count or 1))
    seen_pids: set[str] = set()
    for entry in top_wishlisted:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id in seen_pids:
            continue
        try:
            count = int(entry.get("wishlist_count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count < threshold:
            continue
        seen_pids.add(product_id)
        title = str(entry.get("title") or "").strip()
        proposals.append({
            "product_id": product_id,
            "title": title,
            "wishlist_count": count,
            "tag": _WISHLIST_TAG,
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
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
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
                "wishlist tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
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
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
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
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
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
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``product_id`` + ``tag``. Dispatcher
        # (``tag_wishlisted_hot``) translates to
        # ``{id, tags: [tag]}`` for SHOPIFY_ADD_TAGS.
        params = {
            "product_id": p["product_id"],
            "tag": p["tag"],
            "title": p["title"],
            "wishlist_count": p["wishlist_count"],
        }
        title_part = f" ({p['title']})" if p["title"] else ""
        narrative = (
            f"wishlist: tag product {p['product_id']}{title_part} "
            f"as hot ({p['wishlist_count']} wishlists) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="wishlist",
                action_type="tag_wishlisted_hot",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "wishlist enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "title": p["title"],
                "wishlist_count": p["wishlist_count"],
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
            "title": p["title"],
            "wishlist_count": p["wishlist_count"],
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
            engine="wishlist",
            action_type="tag_wishlisted_hot",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "wishlist record_writeback raised for %s: %s",
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
