"""Dropshipping Engine -- thin-margin tag applier.

Bridges the engine's ``margin_analysis`` list into Shopify
product updates. Products with low gross-margin from their
current dropshipping supplier get tagged so the operator can
either renegotiate the supplier price or raise the selling
price.

Tag composition (worst margin per product across suppliers):
  * ``margin:thin``  -- margin_pct < 15 (barely profitable)
  * ``margin:tight`` -- margin_pct < 25 AND >= 15 (watch)

Healthy margins (>= 25%) silently skipped.

Dedup: if a product is sourced from multiple suppliers, the
WORST margin determines the tag (most conservative).

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.dropshipping.tag_applier")


_THIN_TAG = "margin:thin"
_TIGHT_TAG = "margin:tight"
_THIN_THRESHOLD = 15.0
_TIGHT_THRESHOLD = 25.0


def apply_thin_margin_tags(
    margin_analysis: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products with low gross-margin signals.

    Args:
        margin_analysis: From ``DropshippingEngine.run()``'s
            ``data.margin_analysis``. Each carries
            ``product_id``, ``supplier_id``, ``margin_pct``.
        products: Input list -- merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(margin_analysis, list) or not margin_analysis:
        return []

    # Dedup by product: keep the WORST margin per product.
    worst_per_pid: dict[str, dict[str, Any]] = {}
    for m in margin_analysis:
        if not isinstance(m, dict):
            continue
        pid = str(m.get("product_id", "")).strip()
        if not pid:
            continue
        pct = _margin_pct(m)
        if pct >= _TIGHT_THRESHOLD:
            continue
        prior = worst_per_pid.get(pid)
        if prior is None or _margin_pct(prior) > pct:
            worst_per_pid[pid] = m

    if not worst_per_pid:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(pid, "router_unavailable",
                         margin_pct=_margin_pct(m))
            for pid, m in worst_per_pid.items()
        ]

    results: list[dict[str, Any]] = []
    for pid, m in worst_per_pid.items():
        pct = _margin_pct(m)
        tag = _THIN_TAG if pct < _THIN_THRESHOLD else _TIGHT_TAG

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, [tag])

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "margin_pct": pct,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "margin_pct": pct,
            "supplier_id": str(m.get("supplier_id", "")),
            "tag": tag,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_thin_margin_tags raised for %s: %s",
                pid, exc,
            )
            record_writeback(
                engine="dropshipping",
                action_type="apply_thin_margin_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "margin_pct": pct,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_thin_margin_tags failed for %s: %s",
                pid, err,
            )
            record_writeback(
                engine="dropshipping",
                action_type="apply_thin_margin_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "margin_pct": pct,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="dropshipping",
            action_type="apply_thin_margin_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "margin_pct": pct,
            "error": None,
        })

    return results


def _margin_pct(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("margin_pct", 0.0) or 0.0)
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


def _skip_result(
    pid: str, error: str, *, margin_pct: float = 0.0,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "margin_pct": margin_pct,
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "dropshipping tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "dropshipping tag_applier capability lookup raised: %s",
            exc,
        )
        return None
