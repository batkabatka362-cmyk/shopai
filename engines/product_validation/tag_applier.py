"""Product Validation Engine -- Shopify validation-failure tag
applier.

Bridges the engine's validated product list into Shopify
product updates. Each product that FAILED validation (passed
== False) gets tagged so operators can filter the admin
catalog by validation issues + downstream systems can route
them to manual review queues.

Tags written per failed product:
  * ``validation:failed`` (generic marker)
  * ``validation:risk_<level>`` (risk level: high / critical /
    medium / low / unknown)

Same merge semantics as other Phase 7 tag appliers. Passing
products are silently SKIPPED (the operator's filter is "what
needs review?", not "what's healthy?").

Records via Pattern Z.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_validation.tag_applier")


_GENERIC_FAILED_TAG = "validation:failed"


def apply_validation_tags(
    validated_products: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products that FAILED validation via
    SHOPIFY_UPDATE_PRODUCT.

    Args:
        validated_products: From
            ``ProductValidationEngine.run()``'s
            ``data.validated_products``. Each carries
            ``id`` + ``passed`` + ``risk_level``.
        products: Input list -- merge base for existing tags.

    Returns:
        Per-failed-product results dict.
    """
    if not isinstance(validated_products, list) or not validated_products:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(v), "router_unavailable")
            for v in validated_products
            if isinstance(v, dict)
            and _product_id(v)
            and v.get("passed") is False
        ]

    results: list[dict[str, Any]] = []
    for v in validated_products:
        if not isinstance(v, dict):
            continue
        pid = _product_id(v)
        passed = v.get("passed")
        if not pid or passed is not False:
            # Passing products / no-pid silently skipped --
            # the operator filter is for failures only.
            continue

        risk = str(v.get("risk_level", "unknown")).lower()
        new_tags = [
            _GENERIC_FAILED_TAG,
            f"validation:risk_{risk}",
        ]
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "risk_level": risk,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "risk_level": risk,
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
                "apply_validation_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="product_validation",
                action_type="apply_validation_tags",
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
                "risk_level": risk,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_validation_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="product_validation",
                action_type="apply_validation_tags",
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
                "risk_level": risk,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="product_validation",
            action_type="apply_validation_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
            "risk_level": risk,
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
        "risk_level": "unknown",
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
