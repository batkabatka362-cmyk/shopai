"""Product Scoring Engine -- Shopify tier-tag applier.

Bridges the engine's scored products list into actual Shopify
product updates. Each tier-A product (composite_score >= 7.5)
gets tagged so operators can filter the admin catalog by
scoring-validated SKUs + themes can promote them.

Tags written per tier-A product:
  * ``scoring:tier_a`` (generic marker so a single filter
    pulls every tier-A product)
  * ``scoring:high_composite`` (semantic alias for theme
    queries that don't speak in tier letters)

Same merge semantics as ``product_ranking.tag_applier`` +
``product_research.winner_applier``: SHOPIFY_UPDATE_PRODUCT
REPLACES the tags field, so we read existing tags from the
input products list and merge case-insensitive.

Tier B / C / D are silently SKIPPED (absent from results).
Promoting tier B+ would dilute the filter; if operators
want a wider promotion they can change the threshold here
(but tier A is the bible-aligned high-conviction set).

Skipped (no API call) per product when:
  * tier != "A"
  * product_id can't be matched in the products list
  * all target tags already exist (no-op)
  * router unavailable / adapter rejection / adapter raise

Records via Pattern Z.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_scoring.tag_applier")


# Only tier A earns the tag. B/C/D below high-conviction
# floor; operators tune via the engine config if a niche
# needs wider promotion.
_TAGGABLE_TIERS = {"A"}

_GENERIC_TIER_A_TAG = "scoring:tier_a"
_SEMANTIC_TIER_A_TAG = "scoring:high_composite"


def apply_tier_tags(
    scored_products: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag tier-A scored products with ``scoring:tier_a`` +
    ``scoring:high_composite`` via SHOPIFY_UPDATE_PRODUCT.

    Args:
        scored_products: From
            ``ProductScoringEngine.run()``'s
            ``data.scored_products``. Each carries ``id``
            (or ``product_id``) + ``tier``.
        products: Input products list -- merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(scored_products, list) or not scored_products:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(p), "router_unavailable")
            for p in scored_products
            if isinstance(p, dict)
            and _product_id(p)
            and str(p.get("tier", "")).upper() in _TAGGABLE_TIERS
        ]

    results: list[dict[str, Any]] = []
    for scored in scored_products:
        if not isinstance(scored, dict):
            continue
        pid = _product_id(scored)
        tier = str(scored.get("tier", "")).upper()
        if not pid or tier not in _TAGGABLE_TIERS:
            continue

        new_tags = [_GENERIC_TIER_A_TAG, _SEMANTIC_TIER_A_TAG]
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "tier": tier,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "tier": tier,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability,
                {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_tier_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="product_scoring",
                action_type="apply_tier_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "tier": tier,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_tier_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="product_scoring",
                action_type="apply_tier_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "tier": tier,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="product_scoring",
            action_type="apply_tier_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "tier": tier,
            "error": None,
        })

    return results


# ── Helpers ───────────────────────────────────────────────────


def _product_id(item: dict[str, Any]) -> str:
    pid = item.get("product_id") or item.get("id") or ""
    return str(pid).strip()


def _build_existing_tags_map(
    products: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not isinstance(products, list):
        return out
    for product in products:
        if not isinstance(product, dict):
            continue
        pid = str(
            product.get("product_id")
            or product.get("id")
            or "",
        ).strip()
        if not pid:
            continue
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, list):
            out[pid] = [str(t) for t in tags if t]
    return out


def _merge_tags(
    existing: list[str],
    new: list[str],
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


def _skip_result(pid: str, error: str) -> dict[str, Any]:
    return {
        "product_id": pid,
        "applied": False,
        "tags_added": 0,
        "merged_tags": [],
        "tier": "A",
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "tag_applier capability lookup raised: %s", exc,
        )
        return None
