"""Product Ranking Engine -- top-N rank tag applier.

The engine sorts every product in the catalog by a weighted
final_score and assigns a ``rank`` (1 = best). Pre-fix the
rank signal landed in engine output only -- the merchant had
to manually translate "rank <= 10" into a Shopify segment /
collection that the storefront / email engine could target.

This applier closes the loop. Take the top-N (default 10)
ranked products and push ``shopai-rank-top`` on each via
``SHOPIFY_ADD_TAGS`` (the additive tagsAdd mutation --
existing tags preserved). Merchants then save admin searches
for the tag, build "top picks" smart collections, AND
downstream engines (email_marketing / storefront) filter on
it to feature top-ranked SKUs in homepage carousels,
"featured" sections, or upsell slots.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_ranking_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately per top product.
  data.apply_ranking_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The ``top_n`` parameter (default
10) lives in input data so callers can tune cohort size
without changing the engine output shape.

Skipped (no API call / no queue entry) when:
  * The product has no product_id
  * rank is missing / non-integer / > top_n
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_ranking.tag_applier")


_RANK_TAG = "shopai-rank-top"
_DEFAULT_TOP_N = 10


def apply_ranking_tags(
    ranked_products: list[dict[str, Any]],
    *,
    top_n: int = _DEFAULT_TOP_N,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-rank-top`` on each top-N ranked product.

    Returns per-product list with
    ``{product_id, rank, tag, applied, error}``. When
    ``require_approval=True`` (default), ``applied`` is False
    for queue-only entries -- the actual tag lands when the
    dispatcher executes the approved action.
    ``pending_action_id`` is populated for those entries.
    """
    proposals = _build_proposals(ranked_products, top_n=top_n)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    ranked_products: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Filter ranked products to top-N actionable rows."""
    if not isinstance(ranked_products, list):
        return []
    n = max(1, int(top_n or 1))
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in ranked_products:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        try:
            rank = int(entry.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank < 1 or rank > n:
            continue
        seen.add(product_id)
        title = str(entry.get("title") or "").strip()
        proposals.append({
            "product_id": product_id,
            "title": title,
            "rank": rank,
            "tag": _RANK_TAG,
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
                "rank": p["rank"],
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
                "product_ranking tag_product raised for %s: %s",
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
                "rank": p["rank"],
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
                "rank": p["rank"],
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
                "rank": p["rank"],
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
                "rank": p["rank"],
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
            "rank": p["rank"],
            "title": p["title"],
        }
        title_part = f" ({p['title']})" if p["title"] else ""
        narrative = (
            f"product_ranking: tag product {p['product_id']}"
            f"{title_part} as top-ranked "
            f"(rank #{p['rank']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="product_ranking",
                action_type="tag_ranking_top",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_ranking enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "title": p["title"],
                "rank": p["rank"],
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
            "rank": p["rank"],
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
            engine="product_ranking",
            action_type="tag_ranking_top",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_ranking record_writeback raised for %s: %s",
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
