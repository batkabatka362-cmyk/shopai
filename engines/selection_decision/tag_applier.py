"""Selection Decision Engine -- per-product selected-verdict tag applier.

The engine fuses decision-matrix scores with hard-constraint
checks to emit a per-product ``selected`` / ``rejected``
verdict plus confidence + reasons. Pre-fix the verdict landed
in engine output only -- merchants had to manually translate
"this product cleared our investment matrix at 0.87 confidence"
into a Shopify segment.

This applier closes the loop. For products with
``verdict=selected``, push ``shopai-selection-selected`` on
the product via ``SHOPIFY_ADD_TAGS`` (additive -- existing
tags preserved). Merchants then save admin searches to drive
an "AI-approved investment list" worklist; downstream engines
(catalog / storefront / paid_ads) can prioritise these for
featured slots, ad spend, and homepage carousels.

Distinct from ``shopai-filter-rejected-*`` (product_filter
tags) which marks LOSERS that fell out of the funnel, and
``shopai-tier-A`` (product_scoring) which marks the TOP of a
catalog-wide distribution. selection_decision is the
*portfolio-level* yes/no decision after constraint checks --
a product can be tier-B but still be "selected" for this
quarter's investment portfolio, or vice versa.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_selection_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_selection_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The ``min_confidence`` threshold
(default 0.0 -- tag every selected) lets callers filter to
only high-confidence picks.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id (or "unknown" literal)
  * The verdict isn't ``selected``
  * confidence falls below ``min_confidence``
  * Duplicate product_ids deduped (highest-confidence wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.selection_decision.tag_applier")


_TAG = "shopai-selection-selected"


def apply_selection_tags(
    selected: list[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-selection-selected`` on each selected product.

    Each entry in ``selected`` is
    ``{product_id, title, verdict, confidence, reasons}``.
    Returns per-product list with
    ``{product_id, confidence, verdict, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries.
    """
    proposals = _build_proposals(
        selected, min_confidence=min_confidence,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    selected: list[dict[str, Any]],
    *,
    min_confidence: float,
) -> list[dict[str, Any]]:
    """Filter selected entries to actionable per-product rows."""
    if not isinstance(selected, list):
        return []
    threshold = max(0.0, float(min_confidence or 0.0))

    best: dict[str, dict[str, Any]] = {}
    for entry in selected:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        verdict = str(
            entry.get("verdict") or "",
        ).strip().lower()
        if verdict != "selected":
            continue
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < threshold:
            continue
        title = str(entry.get("title") or "").strip()

        existing = best.get(product_id)
        if existing is None or confidence > existing["confidence"]:
            best[product_id] = {
                "product_id": product_id,
                "verdict": verdict,
                "confidence": round(confidence, 4),
                "title": title,
                "tag": _TAG,
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
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
                "selection_decision tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
            "verdict": p["verdict"],
            "confidence": p["confidence"],
            "title": p["title"],
        }
        narrative = (
            f"selection_decision: tag product {p['product_id']} "
            f"as selected (confidence {p['confidence']}) -> "
            f"{p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="selection_decision",
                action_type="tag_selection_selected",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "selection_decision enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "verdict": p["verdict"],
                "confidence": p["confidence"],
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
            "verdict": p["verdict"],
            "confidence": p["confidence"],
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
            engine="selection_decision",
            action_type="tag_selection_selected",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "selection_decision record_writeback raised for %s: %s",
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
