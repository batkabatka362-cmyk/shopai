"""Competitor Monitor Engine -- undercut tag applier.

Bridges the engine's ``price_changes`` list into Shopify
product updates. OUR products being undercut by competitors
(direction=competitor_lower) get tagged so the pricing engine,
homepage, and merchandising surfaces can react.

Two-tier composition based on undercut magnitude:
  * ``competitor:undercut``     -- abs(change_pct) >= 5
  * ``competitor:severe_undercut`` -- abs(change_pct) >= 15

Only competitor_lower changes (THEY are cheaper than US) tag.
Competitor_higher and aligned-price changes silently skipped.

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.competitor_monitor.tag_applier")


_UNDERCUT_TAG = "competitor:undercut"
_SEVERE_TAG = "competitor:severe_undercut"
_UNDERCUT_THRESHOLD = 5.0   # percent
_SEVERE_THRESHOLD = 15.0    # percent


def apply_undercut_tags(
    price_changes: list[dict[str, Any]],
    our_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag undercut products via SHOPIFY_UPDATE_PRODUCT.

    Args:
        price_changes: From ``CompetitorMonitorEngine.run()``'s
            ``data.price_changes``. Each carries ``product_id``,
            ``direction``, ``change_pct``.
        our_products: Input list -- merge base.

    Returns:
        Per-product results list. Dedup by product_id (one
        product may be undercut by multiple competitors;
        applier writes the tag once).
    """
    if not isinstance(price_changes, list) or not price_changes:
        return []

    # Reduce: pick the WORST undercut per product (largest abs
    # change_pct). One Shopify write per product, not per
    # competitor.
    worst_per_pid: dict[str, dict[str, Any]] = {}
    for change in price_changes:
        if not isinstance(change, dict):
            continue
        if str(change.get("direction", "")) != "competitor_lower":
            continue
        pid = str(change.get("product_id", "")).strip()
        if not pid:
            continue
        pct = abs(_change_pct(change))
        if pct < _UNDERCUT_THRESHOLD:
            continue
        prior = worst_per_pid.get(pid)
        if prior is None or abs(_change_pct(prior)) < pct:
            worst_per_pid[pid] = change

    if not worst_per_pid:
        return []

    existing_by_id = _build_existing_tags_map(our_products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(pid, "router_unavailable")
            for pid in worst_per_pid
        ]

    results: list[dict[str, Any]] = []
    for pid, change in worst_per_pid.items():
        pct = abs(_change_pct(change))
        new_tags = [_UNDERCUT_TAG]
        if pct >= _SEVERE_THRESHOLD:
            new_tags.append(_SEVERE_TAG)

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "undercut_pct": pct,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "undercut_pct": pct,
            "competitor": str(change.get("competitor", "")),
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_undercut_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="competitor_monitor",
                action_type="apply_undercut_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "undercut_pct": pct,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_undercut_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="competitor_monitor",
                action_type="apply_undercut_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "undercut_pct": pct,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="competitor_monitor",
            action_type="apply_undercut_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "undercut_pct": pct,
            "error": None,
        })

    return results


def _change_pct(change: dict[str, Any]) -> float:
    try:
        return float(change.get("change_pct", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# -- Helpers ---------------------------------------------------


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
            or product.get("id") or "",
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


def _skip_result(pid: str, error: str) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "undercut_pct": 0.0,
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "competitor_monitor tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "competitor_monitor tag_applier capability lookup raised: %s",
            exc,
        )
        return None
