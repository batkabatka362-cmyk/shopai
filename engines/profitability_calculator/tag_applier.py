"""Profitability Calculator Engine -- per-product margin tag applier.

The engine computes per-product profitability metrics
(``revenue``, ``total_cost``, ``net_margin``,
``break_even_units``, ``roi``) from product sales data.
Pre-fix the high-margin signal landed in engine output only --
merchants had to manually translate "this product is a 65%
net margin" into a Shopify admin worklist.

This applier closes the loop. For products with
``net_margin >= min_margin`` (default 0.40 = 40%) push
``shopai-margin-high`` on the product via ``SHOPIFY_ADD_TAGS``
(additive -- existing tags preserved). For products with
``net_margin < loss_margin`` (default 0.0 -- selling at a
loss) push ``shopai-margin-negative`` (opt-in via
``include_negative=True``).

Merchants then save admin searches to drive an "investment
priority" worklist (high-margin SKUs deserve more ad spend
and featured slots); downstream engines (paid_ads / catalog
/ storefront) prefer high-margin products for promotion.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_margin_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_margin_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id (or "unknown" literal)
  * net_margin falls between thresholds (middle band is
    noise)
  * Negative-margin tagging requires explicit
    ``include_negative=True``
  * Duplicate product_ids deduped (highest margin wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.profitability_calculator.tag_applier")


_HIGH_TAG = "shopai-margin-high"
_NEGATIVE_TAG = "shopai-margin-negative"
_DEFAULT_MIN_MARGIN = 0.40
_DEFAULT_LOSS_MARGIN = 0.0


def apply_margin_tags(
    profitability: list[dict[str, Any]],
    *,
    min_margin: float = _DEFAULT_MIN_MARGIN,
    loss_margin: float = _DEFAULT_LOSS_MARGIN,
    include_negative: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-margin-{high|negative}`` on flagged products.

    Each entry in ``profitability`` is
    ``{product_id, revenue, total_cost, net_margin,
    break_even_units, roi}``. Returns per-product list with
    ``{product_id, net_margin, bucket, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries.
    """
    proposals = _build_proposals(
        profitability,
        min_margin=min_margin,
        loss_margin=loss_margin,
        include_negative=include_negative,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    profitability: list[dict[str, Any]],
    *,
    min_margin: float,
    loss_margin: float,
    include_negative: bool,
) -> list[dict[str, Any]]:
    """Filter profitability rows to actionable per-product tags."""
    if not isinstance(profitability, list):
        return []
    high_threshold = float(min_margin)
    loss_threshold = float(loss_margin)

    best: dict[str, dict[str, Any]] = {}
    for entry in profitability:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        try:
            net_margin = float(entry.get("net_margin", 0.0))
        except (TypeError, ValueError):
            continue

        bucket: str | None = None
        tag: str | None = None
        if net_margin >= high_threshold:
            bucket = "high"
            tag = _HIGH_TAG
        elif include_negative and net_margin < loss_threshold:
            bucket = "negative"
            tag = _NEGATIVE_TAG
        if bucket is None or tag is None:
            continue

        try:
            roi = float(entry.get("roi", 0.0))
        except (TypeError, ValueError):
            roi = 0.0
        try:
            revenue = float(entry.get("revenue", 0.0))
        except (TypeError, ValueError):
            revenue = 0.0

        existing = best.get(product_id)
        # Highest-margin wins per product.
        if existing is None or net_margin > existing["net_margin"]:
            best[product_id] = {
                "product_id": product_id,
                "net_margin": round(net_margin, 4),
                "roi": round(roi, 4),
                "revenue": round(revenue, 2),
                "bucket": bucket,
                "tag": tag,
            }
    return list(best.values())


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
                "net_margin": p["net_margin"],
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
                "profitability tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "net_margin": p["net_margin"],
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
                "net_margin": p["net_margin"],
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
                "net_margin": p["net_margin"],
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
                "net_margin": p["net_margin"],
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
            "net_margin": p["net_margin"],
            "roi": p["roi"],
            "revenue": p["revenue"],
        }
        narrative = (
            f"profitability: tag product {p['product_id']} as "
            f"{p['bucket']}-margin (net "
            f"{p['net_margin']:.1%}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="profitability_calculator",
                action_type="tag_profitability_margin",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "profitability enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "net_margin": p["net_margin"],
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
            "net_margin": p["net_margin"],
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
            engine="profitability_calculator",
            action_type="tag_profitability_margin",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "profitability record_writeback raised for %s: %s",
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
