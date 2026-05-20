"""Image Optimization Engine -- per-product image-quality tag applier.

The engine analyzes a product's image gallery and emits
``quality_scores`` (average, excellent_count, poor_count) plus
``missing_types`` (required image types the gallery lacks --
hero shot, detail, in-use, etc). Pre-fix the diagnosis landed
in engine output only -- the merchant had to manually
translate "this product has 2 poor-quality images and is
missing a hero shot" into a Shopify admin worklist.

This applier closes the loop. When the analysis flags
fixable problems (any poor-rated image OR any missing
required image type), push ``shopai-image-needs-work`` on
the product via ``SHOPIFY_ADD_TAGS`` (the additive tagsAdd
mutation -- existing tags preserved). Merchants then save
admin searches / smart collections to drive a "products
needing photo work" worklist; downstream engines
(catalog / storefront) can suppress these from featured
slots until the issues are fixed.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_image_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_image_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on. The engine processes ONE product
per run; this applier's list-shaped API stays consistent with
the other writers (callers can batch externally, or supply a
single-item list).

Skipped (no API call / no queue entry) when:
  * The entry has no product_id (anonymous gallery analysis)
  * poor_count == 0 AND missing_types is empty (gallery is
    healthy -- merchants want signal, not noise)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.image_optimization.tag_applier")


_TAG = "shopai-image-needs-work"


def apply_image_tags(
    diagnoses: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-image-needs-work`` on each flagged product.

    Each entry in ``diagnoses`` is
    ``{product_id, quality_scores, missing_types}``. Returns
    per-product list with
    ``{product_id, poor_count, missing_types, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(diagnoses)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    diagnoses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter diagnoses to actionable per-product rows."""
    if not isinstance(diagnoses, list):
        return []
    seen: set[str] = set()
    proposals: list[dict[str, Any]] = []
    for entry in diagnoses:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        quality_scores = entry.get("quality_scores") or {}
        if not isinstance(quality_scores, dict):
            quality_scores = {}
        try:
            poor_count = int(quality_scores.get("poor_count", 0) or 0)
        except (TypeError, ValueError):
            poor_count = 0
        missing_types_raw = entry.get("missing_types") or []
        if not isinstance(missing_types_raw, list):
            missing_types_raw = []
        missing_types = [
            str(m).strip() for m in missing_types_raw
            if str(m or "").strip()
        ]
        if poor_count == 0 and not missing_types:
            continue
        seen.add(product_id)
        proposals.append({
            "product_id": product_id,
            "poor_count": poor_count,
            "missing_types": missing_types,
            "tag": _TAG,
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
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
                "image_optimization tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
            "poor_count": p["poor_count"],
            "missing_types": p["missing_types"],
        }
        reasons = []
        if p["poor_count"] > 0:
            reasons.append(f"{p['poor_count']} poor-quality images")
        if p["missing_types"]:
            reasons.append(
                f"missing types: {', '.join(p['missing_types'])}",
            )
        reasons_part = "; ".join(reasons) if reasons else "image issues"
        narrative = (
            f"image_optimization: tag product {p['product_id']} "
            f"as needing image work ({reasons_part}) -> "
            f"{p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="image_optimization",
                action_type="tag_image_needs_work",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "image_optimization enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "poor_count": p["poor_count"],
                "missing_types": p["missing_types"],
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
            "poor_count": p["poor_count"],
            "missing_types": p["missing_types"],
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
            engine="image_optimization",
            action_type="tag_image_needs_work",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "image_optimization record_writeback raised for %s: %s",
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
