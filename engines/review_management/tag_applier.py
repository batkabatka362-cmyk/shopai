"""Review Management Engine -- review-health tag applier.

Bridges the engine's review summary into Shopify product
updates. Products with review health issues get tagged so
operators can filter the catalog by review status without
re-running the engine.

Multi-signal composition (signals stack -- a product can be
poor AND declining):
  * ``reviews:poor_rating``       -- avg_rating < 3.0 AND
                                     total_reviews >= 5
  * ``reviews:negative_sentiment`` -- sentiment.negative_pct > 50
  * ``reviews:declining``         -- trend.direction = "declining"

Min-review threshold (5) on poor_rating prevents tagging from
a single 1-star outlier on a new product.

Single-product engine -- writeback is per-call (the engine
runs once per product_id), unlike list-based appliers.

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.review_management.tag_applier")


_POOR_TAG = "reviews:poor_rating"
_NEGATIVE_TAG = "reviews:negative_sentiment"
_DECLINING_TAG = "reviews:declining"
_POOR_RATING_THRESHOLD = 3.0
_MIN_REVIEWS_FOR_POOR = 5
_NEGATIVE_PCT_THRESHOLD = 50.0


def apply_review_health_tags(
    product_id: str,
    summary: dict[str, Any],
    sentiment: dict[str, Any],
    trend: dict[str, Any],
    existing_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Tag product based on review-health signals.

    Args:
        product_id: Shopify product GID. Empty -> skipped.
        summary: ``summary`` field from engine output
            (avg_rating, total_reviews).
        sentiment: ``sentiment`` field (negative_pct).
        trend: ``trend`` field (direction).
        existing_tags: Current product tags (merge base). If
            None, applier writes only the new tags (caller
            should pre-fetch for safe merge).

    Returns:
        Result dict with applied / tags_added / merged_tags /
        signals / error.
    """
    pid = str(product_id or "").strip()
    if not pid:
        return _skip_result("", "no_product_id")

    signals = _collect_signals(summary, sentiment, trend)
    if not signals:
        return _skip_result(pid, "no_health_signals")

    new_tags = [_signal_to_tag(s) for s in signals]

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return _skip_result(pid, "router_unavailable", signals)

    existing = list(existing_tags or [])
    merged, added_count = _merge_tags(existing, new_tags)

    if added_count == 0:
        return {
            "product_id": pid, "applied": False,
            "tags_added": 0, "merged_tags": merged,
            "signals": signals,
            "error": "no_new_tags",
        }

    recorder_params = {
        "product_id": pid,
        "signals": signals,
        "tags_added": added_count,
        "total_tags": len(merged),
        "avg_rating": float(summary.get("avg_rating", 0.0) or 0.0),
        "total_reviews": int(summary.get("total_reviews", 0) or 0),
    }

    try:
        result = router.execute(
            capability, {"id": pid, "tags": merged},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "apply_review_health_tags raised for %s: %s", pid, exc,
        )
        record_writeback(
            engine="review_management",
            action_type="apply_review_health_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "product_id": pid, "applied": False,
            "tags_added": 0, "merged_tags": merged,
            "signals": signals,
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        logger.debug(
            "apply_review_health_tags failed for %s: %s", pid, err,
        )
        record_writeback(
            engine="review_management",
            action_type="apply_review_health_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "product_id": pid, "applied": False,
            "tags_added": 0, "merged_tags": merged,
            "signals": signals,
            "error": f"adapter_failed: {err}",
        }

    record_writeback(
        engine="review_management",
        action_type="apply_review_health_tags",
        capability="SHOPIFY_UPDATE_PRODUCT",
        params=recorder_params,
        success=True,
    )
    return {
        "product_id": pid, "applied": True,
        "tags_added": added_count, "merged_tags": merged,
        "signals": signals,
        "error": None,
    }


def _collect_signals(
    summary: dict[str, Any],
    sentiment: dict[str, Any],
    trend: dict[str, Any],
) -> list[str]:
    """Decide which health signals fire for this product."""
    out: list[str] = []
    try:
        avg = float(summary.get("avg_rating", 0.0) or 0.0)
        total = int(summary.get("total_reviews", 0) or 0)
    except (TypeError, ValueError):
        avg, total = 0.0, 0
    if avg < _POOR_RATING_THRESHOLD and total >= _MIN_REVIEWS_FOR_POOR:
        out.append("poor_rating")

    try:
        neg = float(sentiment.get("negative_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        neg = 0.0
    if neg > _NEGATIVE_PCT_THRESHOLD:
        out.append("negative_sentiment")

    if str(trend.get("direction", "")).lower() == "declining":
        out.append("declining")

    return out


def _signal_to_tag(signal: str) -> str:
    return {
        "poor_rating": _POOR_TAG,
        "negative_sentiment": _NEGATIVE_TAG,
        "declining": _DECLINING_TAG,
    }.get(signal, f"reviews:{signal}")


# -- Helpers ---------------------------------------------------


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
    pid: str,
    error: str,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "signals": list(signals or []),
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_management tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "review_management tag_applier capability lookup raised: %s",
            exc,
        )
        return None
