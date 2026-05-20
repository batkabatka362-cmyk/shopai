"""Product Validation Engine -- per-product validation-failed tag applier.

The engine runs compliance / sourcing / quality / risk checks
on each candidate product and emits a per-product
``validated_products`` list with a ``passed`` bool, a
``risk_level``, and a human-readable ``recommendation``
(approve / review / reject). Pre-fix the failure signal
landed in engine output only -- merchants had to manually
translate "this product failed our validation pipeline" into
a Shopify admin worklist.

This applier closes the loop. For products that FAILED
validation (passed=False), push ``shopai-validation-failed``
on the product via ``SHOPIFY_ADD_TAGS`` (additive -- existing
tags preserved). Merchants then save admin searches to drive
a "products needing review before publish" worklist;
downstream engines (catalog / storefront / paid_ads) can
suppress these from featured slots, pause ads, or gate them
on compliance review before promoting.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_validation_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_validation_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no id (or "unknown" literal)
  * passed=True (validation passed -- nothing to tag)
  * Duplicate ids deduped (worst-risk wins -- shouldn't
    happen but be defensive)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_validation.tag_applier")


_TAG = "shopai-validation-failed"
# Risk level → numeric priority for "worst-risk wins" dedup
_RISK_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "unknown": 0,
}


def apply_validation_tags(
    validated_products: list[dict[str, Any]],
    *,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-validation-failed`` on each failed product.

    Each entry in ``validated_products`` is
    ``{id, title, risk_level, recommendation, passed}``.
    Returns per-product list with
    ``{product_id, risk_level, recommendation, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(validated_products)
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    validated_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter validated products to failed-only rows."""
    if not isinstance(validated_products, list):
        return []
    worst: dict[str, dict[str, Any]] = {}
    for entry in validated_products:
        if not isinstance(entry, dict):
            continue
        # The engine emits the product id under ``id``.
        product_id = str(entry.get("id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        # passed=True means the product cleared validation —
        # no tag. The engine builds passed = risk_level not
        # in ("high", "critical"), so we only see passed=False
        # for high/critical risks.
        if bool(entry.get("passed", True)):
            continue
        risk_level = str(
            entry.get("risk_level") or "",
        ).strip().lower()
        recommendation = str(
            entry.get("recommendation") or "",
        ).strip()

        existing = worst.get(product_id)
        if existing is None or (
            _RISK_RANK.get(risk_level, 0)
            > _RISK_RANK.get(existing["risk_level"], 0)
        ):
            worst[product_id] = {
                "product_id": product_id,
                "risk_level": risk_level,
                "recommendation": recommendation,
                "tag": _TAG,
            }
    return list(worst.values())


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
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
                "product_validation tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
            "risk_level": p["risk_level"],
            "recommendation": p["recommendation"],
        }
        rec_part = (
            f" [{p['recommendation']}]"
            if p["recommendation"]
            else ""
        )
        narrative = (
            f"product_validation: tag product {p['product_id']} "
            f"as validation-failed ({p['risk_level']}{rec_part}) "
            f"-> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="product_validation",
                action_type="tag_validation_failed",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_validation enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "risk_level": p["risk_level"],
                "recommendation": p["recommendation"],
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
            "risk_level": p["risk_level"],
            "recommendation": p["recommendation"],
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
            engine="product_validation",
            action_type="tag_validation_failed",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_validation record_writeback raised for %s: %s",
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
