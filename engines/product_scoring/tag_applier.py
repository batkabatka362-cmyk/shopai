"""Product Scoring Engine -- per-product composite-tier tag applier.

The engine builds a weighted composite score per product from
demand / margin / competition signals and assigns a tier
classification (A / B / C / D). Pre-fix the tier signal
landed in engine output only -- merchants had to manually
translate "this product is an A-tier" into a Shopify segment.

This applier closes the loop. For top-tier products (A-tier
by default; opt-in for B), push ``shopai-tier-{letter}`` on
the product via ``SHOPIFY_ADD_TAGS`` (additive -- existing
tags preserved). Merchants then save admin searches / smart
collections to drive a "investment-worthy" worklist;
downstream engines (paid_ads / catalog / storefront) prefer
A/B tiers for ad spend, featured slots, and homepage
carousels.

Only ``A`` is tagged by default. ``B`` is opt-in via
``include_b=True``. ``C`` / ``D`` are noise — these tend to
be the long-tail majority of any catalog.

Distinct from ``shopai-rank-top`` (product_ranking tags)
because product_ranking ranks by composite final_score and
emits a top-N cut, while product_scoring bucketizes the WHOLE
catalog into A/B/C/D tiers. A product can be top-10 in
product_ranking AND B-tier here, or vice versa — different
axes, different operational uses.

Two opt-in modes match the established 2-opt-in Phase 6/7
pattern:

  data.apply_scoring_tags=True + data.require_approval=False
    -> SHOPIFY_ADD_TAGS immediately.
  data.apply_scoring_tags=True + data.require_approval=True
    (default) -> enqueue each tag-add proposal via the
    approval queue.

Default OFF preserves the pure-recommendation contract every
existing caller relies on.

Skipped (no API call / no queue entry) when:
  * The entry has no id (or "unknown" literal)
  * Tier isn't ``A`` (or ``B`` when include_b=True)
  * Duplicate ids deduped (best-tier wins)
  * The router is unavailable (direct path)
  * The queue is unavailable (approval path)
  * The adapter raises or rejects (per-product; batch
    continues)
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_scoring.tag_applier")


_TAG_PREFIX = "shopai-tier-"
_A = "A"
_B = "B"
# Tier letter → numeric priority for "best-tier wins" dedup
_TIER_RANK = {_A: 4, _B: 3, "C": 2, "D": 1}


def apply_scoring_tags(
    scored_products: list[dict[str, Any]],
    *,
    include_b: bool = False,
    require_approval: bool = True,
) -> list[dict[str, Any]]:
    """Stamp ``shopai-tier-{A|B}`` on each top-tier product.

    Each entry in ``scored_products`` is the per-product
    composite from the engine: ``{id, title, composite_score,
    tier, ...}``. Returns per-product list with
    ``{product_id, tier, composite_score, tag, applied,
    error}``. When ``require_approval=True`` (default),
    ``applied`` is False for queue-only entries.
    """
    proposals = _build_proposals(
        scored_products, include_b=include_b,
    )
    if not proposals:
        return []
    if require_approval:
        return _enqueue_each(proposals)
    return _apply_each_direct(proposals)


def _build_proposals(
    scored_products: list[dict[str, Any]],
    *,
    include_b: bool,
) -> list[dict[str, Any]]:
    """Filter scored products to actionable per-product rows."""
    if not isinstance(scored_products, list):
        return []
    allowed = {_A}
    if include_b:
        allowed = {_A, _B}

    best: dict[str, dict[str, Any]] = {}
    for entry in scored_products:
        if not isinstance(entry, dict):
            continue
        # The engine emits the product id under ``id``
        # (not ``product_id``) -- match its key.
        product_id = str(entry.get("id") or "").strip()
        if not product_id or product_id == "unknown":
            continue
        tier = str(entry.get("tier") or "").strip().upper()
        if tier not in allowed:
            continue
        try:
            composite = float(entry.get("composite_score", 0.0))
        except (TypeError, ValueError):
            composite = 0.0
        title = str(entry.get("title") or "").strip()

        existing = best.get(product_id)
        if existing is None or (
            _TIER_RANK.get(tier, 0)
            > _TIER_RANK.get(existing["tier"], 0)
        ):
            best[product_id] = {
                "product_id": product_id,
                "tier": tier,
                "composite_score": round(composite, 2),
                "title": title,
                "tag": f"{_TAG_PREFIX}{tier}",
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
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
                "product_scoring tag_product raised for %s: %s",
                p["product_id"], exc,
            )
            _record_writeback_safely(
                product_id=p["product_id"],
                tag=p["tag"], success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": p["product_id"],
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
            "tier": p["tier"],
            "composite_score": p["composite_score"],
            "title": p["title"],
        }
        title_part = f" ({p['title']})" if p["title"] else ""
        narrative = (
            f"product_scoring: tag product {p['product_id']}"
            f"{title_part} as tier {p['tier']} "
            f"(score {p['composite_score']}) -> {p['tag']}"
        )
        try:
            action = queue.enqueue(
                engine="product_scoring",
                action_type="tag_product_tier",
                capability="SHOPIFY_ADD_TAGS",
                params=params,
                narrative=narrative,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "product_scoring enqueue raised for %s: %s",
                p["product_id"], exc,
            )
            results.append({
                "product_id": p["product_id"],
                "tier": p["tier"],
                "composite_score": p["composite_score"],
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
            "tier": p["tier"],
            "composite_score": p["composite_score"],
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
            engine="product_scoring",
            action_type="tag_product_tier",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": product_id, "tag": tag},
            success=success,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "product_scoring record_writeback raised for %s: %s",
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
