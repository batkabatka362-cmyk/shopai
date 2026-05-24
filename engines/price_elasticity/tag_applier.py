"""Price Elasticity Engine -- elasticity tag applier.

Bridges the engine's per-product elasticity coefficients into
Shopify product updates. Products get tagged with their
elasticity profile so pricing + discount engines can make
fast decisions without re-running the elasticity model.

Standard economics convention (|coefficient| > 1 = elastic):
  * ``pricing:elastic``        -- |coef| > 1, demand reacts
                                  strongly to price changes
                                  (discount = bigger volume lift)
  * ``pricing:highly_elastic`` -- |coef| >= 2 (also elastic);
                                  very price-sensitive
  * ``pricing:inelastic``      -- |coef| <= 1 AND non-zero;
                                  demand stable across price
                                  (room to raise without hurting
                                  volume)

Products with coefficient == 0 (insufficient data) silently
skipped -- no signal to act on.

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.price_elasticity.tag_applier")


_ELASTIC_TAG = "pricing:elastic"
_HIGHLY_ELASTIC_TAG = "pricing:highly_elastic"
_INELASTIC_TAG = "pricing:inelastic"
_HIGHLY_ELASTIC_THRESHOLD = 2.0
_ELASTIC_THRESHOLD = 1.0


def apply_elasticity_tags(
    elasticity: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products with their elasticity profile.

    Args:
        elasticity: From ``PriceElasticityEngine.run()``'s
            ``data.elasticity``. Each carries ``product_id``,
            ``coefficient``, ``is_elastic``.
        products: Input list -- merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(elasticity, list) or not elasticity:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(e), "router_unavailable",
                         coefficient=_coefficient(e))
            for e in elasticity
            if isinstance(e, dict)
            and _product_id(e)
            and _coefficient(e) != 0.0
        ]

    results: list[dict[str, Any]] = []
    for entry in elasticity:
        if not isinstance(entry, dict):
            continue
        pid = _product_id(entry)
        coef = _coefficient(entry)
        if not pid or coef == 0.0:
            continue

        new_tags = _compose_tags(coef)
        if not new_tags:
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "coefficient": coef,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "coefficient": coef,
            "is_elastic": bool(entry.get("is_elastic", False)),
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_elasticity_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="price_elasticity",
                action_type="apply_elasticity_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "coefficient": coef,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_elasticity_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="price_elasticity",
                action_type="apply_elasticity_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "coefficient": coef,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="price_elasticity",
            action_type="apply_elasticity_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "coefficient": coef,
            "error": None,
        })

    return results


def _compose_tags(coefficient: float) -> list[str]:
    abs_coef = abs(coefficient)
    if abs_coef >= _HIGHLY_ELASTIC_THRESHOLD:
        return [_ELASTIC_TAG, _HIGHLY_ELASTIC_TAG]
    if abs_coef > _ELASTIC_THRESHOLD:
        return [_ELASTIC_TAG]
    return [_INELASTIC_TAG]


def _coefficient(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("coefficient", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# -- Helpers ---------------------------------------------------


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


def _skip_result(
    pid: str, error: str, *, coefficient: float = 0.0,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "coefficient": coefficient,
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "price_elasticity tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "price_elasticity tag_applier capability lookup raised: %s",
            exc,
        )
        return None
