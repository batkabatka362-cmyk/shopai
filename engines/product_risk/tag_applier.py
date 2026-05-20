"""Product Risk Engine -- per-product risk-level tag applier.

The engine scores each product across four risk dimensions
(market / supply / legal / financial) and aggregates them into
a weighted ``overall`` score plus a ``risk_level`` bucket
(low / moderate / high / critical). Pre-fix the
classification landed in engine output only -- the merchant
had to manually translate "this product hits our high-risk
threshold across legal + supply" into a Shopify segment /
worklist.

This applier closes the loop. For high-risk products, push
``shopai-risk-{level}`` on the product via
``SHOPIFY_ADD_TAGS`` (additive -- existing tags preserved).
``level`` is ``critical`` or ``high``. Merchants then save
admin searches to drive a "products requiring risk review"
worklist; downstream engines (catalog / storefront /
paid_ads) can suppress these from featured slots, pause ad
spend, or gate on legal review before promoting.

Only ``critical`` is tagged by default; ``high`` is opt-in
via ``include_high=True``. ``moderate`` / ``low`` are noise
for the operational worklist.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_risk_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_risk_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The risk entry has no product_id (or "unknown" literal)
  * The risk_level isn't ``critical`` (or ``high`` when
    include_high=True)
  * Duplicate product_ids deduped (worst-risk wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_risk.tag_applier")


_TAG_PREFIX = "shopai-risk-"
_CRITICAL = "critical"
_HIGH = "high"
# Risk level → numeric priority for "worst-risk wins" dedup
_RISK_RANK = {
    _CRITICAL: 4,
    _HIGH: 3,
    "moderate": 2,
    "low": 1,
}


def apply_risk_tags(
    risks: list[dict[str, Any]],
    *,
    include_high: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-risk-{level}`` on each at-risk product.

    Each entry in ``risks`` is the per-product aggregate from
    the engine: ``{product_id, market_risk, supply_risk,
    legal_risk, financial_risk, overall, risk_level}``.
    Returns per-product list with
    ``{product_id, risk_level, overall, tag, applied, error}``.
    When ``require_approval=True`` (default), ``applied`` is
    False for queue-only entries.
    """
    proposals = _build_proposals(
        risks, include_high=include_high,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    risks: list[dict[str, Any]],
    *,
    include_high: bool,
) -> list[dict[str, Any]]:
    """Filter risks to actionable per-product rows.

    Worst-risk wins per product: if the same product_id
    appears twice (rare; defensive), keep the higher level.
    """
    if not isinstance(risks, list):
        return []
    allowed = {_CRITICAL}
    if include_high:
        allowed = {_CRITICAL, _HIGH}

    worst: dict[str, dict[str, Any]] = {}
    for entry in risks:
        if not isinstance(entry, dict):
            continue
        product_id = str(entry.get("product_id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        risk_level = str(
            entry.get("risk_level") or "",
        ).strip().lower()
        if risk_level not in allowed:
            continue
        try:
            overall = float(entry.get("overall", 0.0))
        except (TypeError, ValueError):
            overall = 0.0

        existing = worst.get(product_id)
        if existing is None or (
            _RISK_RANK.get(risk_level, 0)
            > _RISK_RANK.get(existing["risk_level"], 0)
        ):
            worst[product_id] = {
                "product_id": product_id,
                "risk_level": risk_level,
                "overall": round(overall, 3),
                "tag": f"{_TAG_PREFIX}{risk_level}",
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
                "overall": p["overall"],
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
                "product_risk tag_product raised for %s: %s",
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
                "overall": p["overall"],
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
                "overall": p["overall"],
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
                "overall": p["overall"],
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
                "overall": p["overall"],
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
            "overall": p["overall"],
        }
        narrative = (
            f"product_risk: tag product {p['product_id']} "
            f"as {p['risk_level']}-risk (overall "
            f"{p['overall']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="product_risk",
                action_type="tag_product_risk",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_risk enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "risk_level": p["risk_level"],
                "overall": p["overall"],
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
            "overall": p["overall"],
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
            engine="product_risk",
            action_type="tag_product_risk",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_risk record_writeback raised for %s: %s",
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
