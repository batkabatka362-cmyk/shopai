"""Selection Decision Engine -- Shopify selected-product tag
applier.

Bridges the engine's selected list into actual Shopify product
updates. Each selected product gets tagged so operators can
filter the admin catalog by approved SKUs + downstream
collections / smart filters can read the tag.

Tags written per selected product:
  * ``selection:approved`` (generic marker so a single
    filter pulls every selected product)

Same merge semantics as the other Phase 7 tag appliers
(tag_management / product_research / product_ranking /
product_scoring). Records via Pattern Z.

Rejected products are not tagged (they're not promoted to
the filter). Skipped per product when product_id missing,
all tags already exist, or router unavailable.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.selection_decision.tag_applier")


_SELECTION_TAG = "selection:approved"


def apply_selection_tags(
    selected: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag selected products with ``selection:approved`` via
    SHOPIFY_UPDATE_PRODUCT.

    Args:
        selected: From
            ``SelectionDecisionEngine.run()``'s
            ``data.selected``. Each carries ``product_id``.
        products: Input products list -- merge base.

    Returns:
        Per-selected results dict.
    """
    if not isinstance(selected, list) or not selected:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(s), "router_unavailable")
            for s in selected
            if isinstance(s, dict) and _product_id(s)
        ]

    results: list[dict[str, Any]] = []
    for entry in selected:
        if not isinstance(entry, dict):
            continue
        pid = _product_id(entry)
        if not pid:
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(
            existing, [_SELECTION_TAG],
        )

        if added_count == 0:
            results.append({
                "product_id": pid,
                "applied": False,
                "tags_added": 0,
                "merged_tags": merged,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
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
                "apply_selection_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="selection_decision",
                action_type="apply_selection_tags",
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
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_selection_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="selection_decision",
                action_type="apply_selection_tags",
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
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="selection_decision",
            action_type="apply_selection_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid,
            "applied": True,
            "tags_added": added_count,
            "merged_tags": merged,
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
