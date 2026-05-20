"""Warranty Engine -- per-product warranty-risk tag applier.

The engine processes warranty claims, tracks costs, and emits
a per-product ``risk_analysis`` with a ``risk_level``
(high / medium / low) reflecting claim frequency and cost
impact. Pre-fix the signal landed in engine output only --
the merchant had to manually translate "this product has
above-average warranty claims" into a Shopify admin worklist.

This applier closes the loop. For high-risk products (heavy
warranty-claim drain on margin), push
``shopai-warranty-high-risk`` on the product via
``SHOPIFY_ADD_TAGS`` (additive -- existing tags preserved).
Merchants then save admin searches to drive a "warranty
hotspots" worklist; downstream engines (catalog /
storefront / paid_ads) can suppress these from featured
slots, gate them on supplier review, or pause ads on
chronically defective SKUs.

Only ``high`` risk is tagged by default. ``medium`` / ``low``
are noise for the operational worklist.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_warranty_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_warranty_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no product_id
  * The risk_level isn't ``high``
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

logger = get_logger("engines.warranty.tag_applier")


_TAG = "shopai-warranty-high-risk"


def apply_warranty_tags(
    risk_analysis: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-warranty-high-risk`` on each high-risk product.

    Each entry in ``risk_analysis`` is
    ``{product_id, claim_count, total_cost, risk_score,
    risk_level}``. Returns per-product list with
    ``{product_id, claim_count, risk_score, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(risk_analysis)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    risk_analysis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter risk analyses to actionable per-product rows."""
    if not isinstance(risk_analysis, list):
        return []
    seen: dict[str, dict[str, Any]] = {}
    for entry in risk_analysis:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id:
            continue
        risk_level = str(
            entry.get("risk_level") or "",
        ).strip().lower()
        if risk_level != "high":
            continue
        try:
            claim_count = int(entry.get("claim_count", 0) or 0)
        except (TypeError, ValueError):
            claim_count = 0
        try:
            risk_score = float(entry.get("risk_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            risk_score = 0.0
        # Last-seen-wins dedup: the engine should never emit
        # duplicates but be defensive against hand-built data.
        seen[product_id] = {
            "product_id": product_id,
            "claim_count": claim_count,
            "risk_score": round(risk_score, 3),
            "tag": _TAG,
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
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
                "warranty tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
            "claim_count": p["claim_count"],
            "risk_score": p["risk_score"],
        }
        narrative = (
            f"warranty: tag product {p['product_id']} as "
            f"high warranty risk ({p['claim_count']} claims, "
            f"score {p['risk_score']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="warranty",
                action_type="tag_warranty_risk",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "warranty enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "claim_count": p["claim_count"],
                "risk_score": p["risk_score"],
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
            "claim_count": p["claim_count"],
            "risk_score": p["risk_score"],
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
            engine="warranty",
            action_type="tag_warranty_risk",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "warranty record_writeback raised for %s: %s",
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
