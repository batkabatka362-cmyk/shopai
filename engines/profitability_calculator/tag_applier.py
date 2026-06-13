"""Profitability Calculator Engine -- ROI tier tag applier.

Bridges the engine's ``profitability`` list (per-product ROI)
into Shopify product updates. Products are tagged by ROI tier
so merchandising + ad-budget engines can spot WINNERS (high ROI)
and LOSERS (low ROI) without re-running the engine.

Tag composition:
  * ``profit:high_roi`` -- roi >= 200% (winners; deserve more
                           ad budget + featured placement)
  * ``profit:low_roi``  -- roi <= 30%  (losers; cost control
                           or delisting candidates)

Mid-band ROI (30-200%) silently skipped -- normal performance,
no operator action needed.

Same merge semantics + Pattern Z recording as other Phase 7
product-tag appliers.

Complementary to dropshipping's margin:thin/tight tag:
  * dropshipping margin: GROSS margin (selling price - supplier cost)
  * profitability ROI:   NET return (revenue / total_cost - 1)
A product can carry both: thin gross margin AND low ROI is a
double-trouble signal.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.profitability_calculator.tag_applier")


_HIGH_TAG = "profit:high_roi"
_LOW_TAG = "profit:low_roi"
_HIGH_THRESHOLD = 200.0
_LOW_THRESHOLD = 30.0


def apply_roi_tags(
    profitability: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag products with their ROI tier.

    Args:
        profitability: From ``ProfitabilityCalculatorEngine.run()``'s
            ``data.profitability``. Each carries ``product_id``,
            ``roi``.
        products: Input list -- merge base.

    Returns:
        Per-product results dict.
    """
    if not isinstance(profitability, list) or not profitability:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(
                str(p.get("product_id", "")),
                "router_unavailable",
                roi=_roi(p),
            )
            for p in profitability
            if isinstance(p, dict)
            and str(p.get("product_id", "")).strip()
            and _pick_tag(_roi(p))
        ]

    results: list[dict[str, Any]] = []
    for entry in profitability:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("product_id", "")).strip()
        roi = _roi(entry)
        if not pid:
            continue
        tag = _pick_tag(roi)
        if not tag:
            continue

        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, [tag])

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "roi": roi, "tag": tag,
                "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "roi": roi,
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
                "apply_roi_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="profitability_calculator",
                action_type="apply_roi_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "roi": roi, "tag": tag,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_roi_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="profitability_calculator",
                action_type="apply_roi_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "roi": roi, "tag": tag,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="profitability_calculator",
            action_type="apply_roi_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "roi": roi, "tag": tag,
            "error": None,
        })

    return results


def _pick_tag(roi: float) -> str:
    if roi >= _HIGH_THRESHOLD:
        return _HIGH_TAG
    if roi <= _LOW_THRESHOLD:
        return _LOW_TAG
    return ""


def _roi(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("roi", 0.0) or 0.0)
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
    pid: str, error: str, *, roi: float = 0.0,
) -> dict[str, Any]:
    return {
        "product_id": pid, "applied": False,
        "tags_added": 0, "merged_tags": [],
        "roi": roi, "tag": "",
        "error": error,
    }


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "profitability_calculator tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_update_product() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_UPDATE_PRODUCT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "profitability_calculator tag_applier capability lookup raised: %s",
            exc,
        )
        return None
