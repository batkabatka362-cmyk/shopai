"""Cross-Sell Engine -- per-product cross-sell-target tag applier.

The engine ranks complement products to suggest alongside a
cart (case + phone, lens + camera, ...). Pre-fix the
recommendations landed in the engine output only -- the
merchant had to manually translate "this product is suggested
as a cross-sell" into a Shopify segment / collection that the
storefront / email engine could target.

This applier closes the loop. For each recommended cross-sell,
push a tag ``shopai-cross-sell-target`` on the product via
``SHOPIFY_ADD_TAGS`` (the additive tagsAdd mutation -- existing
tags are preserved). Merchants then save a Shopify admin
search for the tag, build smart collections, or downstream
engines (email_marketing / catalog) filter on it to feature
cross-sell candidates in "complete the set"-style campaigns.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_cross_sell_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately per recommendation.
  data.apply_cross_sell_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the approval
    queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The recommendation has no product_id
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.cross_sell.tag_applier")


_CROSS_SELL_TAG = "shopai-cross-sell-target"


def apply_cross_sell_tags(
    recommendations: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-cross-sell-target`` on each recommendation.

    Returns per-product list with
    ``{product_id, title, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries -- the actual tag lands when
    the dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(recommendations)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter the engine's recommendations to actionable rows."""
    proposals: list[dict[str, Any]] = []
    if not isinstance(recommendations, list):
        return proposals
    seen_pids: set[str] = set()
    for r in recommendations:
        if not isinstance(r, dict):
            continue
        product_id = str(r.get("product_id") or "").strip()
        if not product_id or product_id in seen_pids:
            continue
        seen_pids.add(product_id)
        title = str(r.get("title") or "").strip()
        proposals.append({
            "product_id": product_id,
            "title": title,
            "tag": _CROSS_SELL_TAG,
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
                "cross_sell tag_product raised for %s: %s",
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
                "tag": p["tag"],
                "applied": False,
                "error": "approval_queue_unavailable",
            }
            for p in proposals
        ]

    results: list[dict[str, Any]] = []
    for p in proposals:
        # Enqueue uses ``product_id`` + ``tag``. Dispatcher
        # (``tag_cross_sell_target``) translates to
        # ``{id, tags: [tag]}`` for SHOPIFY_ADD_TAGS.
        params = {
            "product_id": p["product_id"],
            "tag": p["tag"],
            "title": p["title"],
        }
        title_part = f" ({p['title']})" if p["title"] else ""
        narrative = (
            f"cross_sell: tag product {p['product_id']}{title_part} "
            f"as cross-sell target -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="cross_sell",
                action_type="tag_cross_sell_target",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "cross_sell enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "title": p["title"],
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
            engine="cross_sell",
            action_type="tag_cross_sell_target",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "cross_sell record_writeback raised for %s: %s",
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
