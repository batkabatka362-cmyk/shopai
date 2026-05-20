"""Review Management Engine -- per-product review-quality tag applier.

The engine aggregates ratings + sentiment for a single product
into ``summary.avg_rating`` and ``sentiment.{positive_pct,
negative_pct}``. Pre-fix the quality signal landed in engine
output only -- the merchant had to manually translate "this
product is 4.8 stars with 90% positive reviews" into a Shopify
admin search / collection that the storefront / email engine
could target.

This applier closes the loop. Based on average rating + minimum
review count, push one of:

  * ``shopai-review-top-rated`` -- avg_rating >= 4.5 AND
    total_reviews >= min_reviews (default 5). High-signal
    upsell + featured-product candidate.
  * ``shopai-review-low-rated`` -- avg_rating <= 2.5 AND
    total_reviews >= min_reviews. Triage candidate;
    downstream engines may suppress from recommendations.

Products in the "middle" (2.5 < avg < 4.5) are intentionally
NOT tagged -- merchants want signal, not noise. Below the
min_reviews floor we also skip: ratings are unreliable with
too few samples.

Tags use ``SHOPIFY_ADD_TAGS`` (additive -- existing tags
preserved). Merchants then save admin searches / smart
collections; downstream engines (email_marketing / catalog /
storefront) filter on the tag to feature top-rated or suppress
low-rated SKUs.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_review_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_review_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * product_id is blank
  * total_reviews falls below ``min_reviews`` (default 5)
  * avg_rating is in the neutral middle (2.5 < x < 4.5)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues if the applier is ever called with multiple
    proposals)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.review_management.tag_applier")


_TAG_PREFIX = "shopai-review-"
_TOP_THRESHOLD = 4.5
_LOW_THRESHOLD = 2.5
_DEFAULT_MIN_REVIEWS = 5


def apply_review_tags(
    summaries: list[dict[str, Any]],
    *,
    min_reviews: int = _DEFAULT_MIN_REVIEWS,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-review-{bucket}`` on each scored product.

    Each entry in ``summaries`` is a per-product summary
    ``{product_id, avg_rating, total_reviews, ...}``. Returns
    per-product list with
    ``{product_id, avg_rating, total_reviews, bucket, tag,
    applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries.
    """
    proposals = _build_proposals(
        summaries, min_reviews=min_reviews,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    summaries: list[dict[str, Any]],
    *,
    min_reviews: int,
) -> list[dict[str, Any]]:
    """Filter summaries to actionable per-product rows."""
    if not isinstance(summaries, list):
        return []
    threshold = max(1, int(min_reviews or 1))
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in summaries:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        try:
            avg_rating = float(entry.get("avg_rating", 0.0))
        except (TypeError, ValueError):
            continue
        try:
            total_reviews = int(entry.get("total_reviews", 0))
        except (TypeError, ValueError):
            continue
        if total_reviews < threshold:
            continue
        bucket = _bucket_for(avg_rating)
        if bucket is None:
            continue
        seen.add(product_id)
        proposals.append({
            "product_id": product_id,
            "avg_rating": round(avg_rating, 2),
            "total_reviews": total_reviews,
            "bucket": bucket,
            "tag": f"{_TAG_PREFIX}{bucket}",
        })
    return proposals


def _bucket_for(avg_rating: float) -> str | None:
    if avg_rating >= _TOP_THRESHOLD:
        return "top-rated"
    if avg_rating <= _LOW_THRESHOLD:
        return "low-rated"
    return None


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
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
                "review tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
            "avg_rating": p["avg_rating"],
            "total_reviews": p["total_reviews"],
            "bucket": p["bucket"],
        }
        narrative = (
            f"review_management: tag product {p['product_id']} "
            f"as {p['bucket']} (avg_rating {p['avg_rating']}, "
            f"{p['total_reviews']} reviews) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="review_management",
                action_type="tag_review_product",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "review enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "avg_rating": p["avg_rating"],
                "total_reviews": p["total_reviews"],
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
            "avg_rating": p["avg_rating"],
            "total_reviews": p["total_reviews"],
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
            engine="review_management",
            action_type="tag_review_product",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review record_writeback raised for %s: %s",
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
