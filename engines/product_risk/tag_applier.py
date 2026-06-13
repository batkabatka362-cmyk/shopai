"""Product Risk Engine -- Shopify high-risk tag applier.

Bridges the engine's risk-scored products into Shopify product
updates. Each high-risk or critical-risk product gets tagged
so operators can filter the admin catalog by risk + downstream
systems route them to manual review.

Tags written per high/critical-risk product:
  * ``risk:high`` (generic marker covering both high and
    critical so a single filter pulls everything actionable)
  * ``risk:<level>`` (high or critical, lets operators
    split by severity)

Same merge semantics + Pattern Z + router-unavailable shape
as the other Phase 7 tag appliers. Low/moderate risk silently
skipped.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.product_risk.tag_applier")


_TAGGABLE_RISK_LEVELS = {"high", "critical"}
_GENERIC_RISK_TAG = "risk:high"


def apply_risk_tags(
    risks: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag high/critical-risk products with ``risk:high`` +
    ``risk:<level>`` via SHOPIFY_UPDATE_PRODUCT.

    Args:
        risks: From ``ProductRiskEngine.run()``'s
            ``data.risks``. Each carries ``product_id`` +
            ``risk_level`` + scores.
        products: Input list -- merge base.

    Returns:
        Per-tagged-product results dict.
    """
    if not isinstance(risks, list) or not risks:
        return []

    existing_by_id = _build_existing_tags_map(products)
    router = _get_router()
    capability = _get_capability_update_product()
    if router is None or capability is None:
        return [
            _skip_result(_product_id(r), "router_unavailable")
            for r in risks
            if isinstance(r, dict)
            and _product_id(r)
            and str(r.get("risk_level", "")).lower()
            in _TAGGABLE_RISK_LEVELS
        ]

    results: list[dict[str, Any]] = []
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        pid = _product_id(risk)
        level = str(risk.get("risk_level", "")).lower()
        if not pid or level not in _TAGGABLE_RISK_LEVELS:
            continue

        new_tags = [_GENERIC_RISK_TAG, f"risk:{level}"]
        existing = existing_by_id.get(pid, [])
        merged, added_count = _merge_tags(existing, new_tags)

        if added_count == 0:
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "risk_level": level, "error": "no_new_tags",
            })
            continue

        recorder_params = {
            "product_id": pid,
            "risk_level": level,
            "tags_added": added_count,
            "total_tags": len(merged),
        }

        try:
            result = router.execute(
                capability, {"id": pid, "tags": merged},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_risk_tags raised for %s: %s", pid, exc,
            )
            record_writeback(
                engine="product_risk",
                action_type="apply_risk_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "risk_level": level,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_risk_tags failed for %s: %s", pid, err,
            )
            record_writeback(
                engine="product_risk",
                action_type="apply_risk_tags",
                capability="SHOPIFY_UPDATE_PRODUCT",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "product_id": pid, "applied": False,
                "tags_added": 0, "merged_tags": merged,
                "risk_level": level,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="product_risk",
            action_type="apply_risk_tags",
            capability="SHOPIFY_UPDATE_PRODUCT",
            params=recorder_params,
            success=True,
        )
        results.append({
            "product_id": pid, "applied": True,
            "tags_added": added_count, "merged_tags": merged,
            "risk_level": level, "error": None,
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
        "risk_level": "unknown", "error": error,
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
