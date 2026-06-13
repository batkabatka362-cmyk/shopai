"""Product Ranking Engine -- Shopify top-tier tag applier.

Bridges the engine's ranked products list into actual Shopify
product updates. Each product in the top tier (rank <= 3) gets
tagged so operators can filter the admin catalog by ranked
SKUs + theme can boost them in search/collection ordering.

Tags written per top-tier product:
  * ``ranking:top_tier`` (generic marker so a single filter
    pulls every top-3 product)
  * ``ranking:rank_<N>`` (rank_1 / rank_2 / rank_3, so themes
    can target the #1 individually)

Same merge semantics as ``tag_management.tag_applier`` +
``product_research.winner_applier``: SHOPIFY_UPDATE_PRODUCT
REPLACES the tags field, so we read existing tags from the
input products list + merge case-insensitive.

Skipped (no API call) per product when:
  * rank > 3 (not top-tier)
  * product_id can't be matched in the products list (need
    existing tags for merge)
  * all new tags already exist (no-op)
  * router unavailable / adapter rejection / adapter raise

Records via Pattern Z so every apply attempt feeds Phase 8's
learning loop -- the system can later correlate top-tier
tagging with downstream catalog signals.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_ranking.tag_applier")


# Maximum rank that earns a top-tier tag. Mirrors the flow's
# top_tier_count cutoff (rank <= 3).
_TOP_TIER_RANK_MAX = 3

# Generic marker tag for the filter-by-single-tag use case.
_GENERIC_TOP_TIER_TAG = "ranking:top_tier"


def apply_top_tier_tags(
    ranked_products: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag top-tier ranked products with ``ranking:top_tier``
    + ``ranking:rank_<N>`` via SHOPIFY_UPDATE_PRODUCT.

    Args:
        ranked_products: Ranked list from
            ``ProductRankingEngine.run()``'s
            ``data.ranked_products``. Each carries
            ``product_id`` (or ``id``) + ``rank``.
        products: Input products list -- source of existing
            tags for merge.

    Returns:
        Per-product list with ``{product_id, applied,
        tags_added, merged_tags, rank, error}``.
    """
    if not isinstance(ranked_products, list) or not ranked_products:
        return []

    existing_by_id = _build_existing_tags_map(products)

    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(
                _product_id(p),
                "router_unavailable",
                rank=int(p.get("rank", 0) or 0),
            )
            for p in ranked_products
            if isinstance(p, dict)
            and _product_id(p)
            and 1 <= int(p.get("rank", 0) or 0)
            <= _TOP_TIER_RANK_MAX
        ]

    results: list[dict[str, Any]] = []
    for ranked in ranked_products:
        if not isinstance(ranked, dict):
            continue

        pid = _product_id(ranked)
        try:
            rank = int(ranked.get("rank", 0) or 0)
        except (TypeError, ValueError):
            rank = 0

        if not pid or rank < 1 or rank > _TOP_TIER_RANK_MAX:
            # Below top tier; silently skipped (no result
            # row).
            continue

        new_tags = [_GENERIC_TOP_TIER_TAG, f"ranking:rank_{rank}"]
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "rank": rank,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "rank": rank,
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
                "apply_top_tier_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="product_ranking",
                action_type="apply_top_tier_tags",
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
                "rank": rank,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_top_tier_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="product_ranking",
                action_type="apply_top_tier_tags",
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
                "rank": rank,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="product_ranking",
            action_type="apply_top_tier_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "rank": rank,
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


def _skip_result(
    pid: str, error: str, *, rank: int = 0,
) -> dict[str, Any]:
    return {
        "product_id": pid,
        "applied": False,
        "tags_added": 0,
        "merged_tags": [],
        "rank": rank,
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
