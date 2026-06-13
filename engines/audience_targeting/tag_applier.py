"""Audience Targeting Engine -- audience segment tag applier.

Bridges the engine's ``match_results`` list into Shopify
CUSTOMER tag updates. Each customer gets tagged with every
segment they match, so marketing engines can target by
segment without re-running the matcher.

Tag format:
  * ``audience:<segment_id>`` -- e.g. audience:high_value,
    audience:frequent_buyers, audience:at_risk

Customers can carry MULTIPLE audience tags simultaneously
(a customer may be both high_value AND frequent_buyers).
SHOPIFY_TAG_CUSTOMER is additive so no merge dance needed.

Third customer-tag wireup (cohort_analysis, customer_journey
were first two). Records via Pattern Z so audience-tagging
fans into the learning loop.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.audience_targeting.tag_applier")


def apply_audience_tags(
    match_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag every matched customer with every audience segment.

    Args:
        match_results: From rule_matcher. Each carries
            ``segment_id`` + ``matched_customer_ids``.

    Returns:
        Per-(customer, segment) results list. Note: one
        customer matching N segments → N result entries.
    """
    if not isinstance(match_results, list) or not match_results:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "customer_id": str(cid),
                "segment_id": str(m.get("segment_id", "")),
                "applied": False,
                "error": "router_unavailable",
            }
            for m in match_results
            if isinstance(m, dict)
            and str(m.get("segment_id", "")).strip()
            for cid in m.get("matched_customer_ids", []) or []
            if cid
        ]

    results: list[dict[str, Any]] = []
    for match in match_results:
        if not isinstance(match, dict):
            continue
        seg_id = str(match.get("segment_id", "")).strip()
        if not seg_id:
            continue
        audience_tag = f"audience:{seg_id}"
        customer_ids = match.get("matched_customer_ids", []) or []

        for cid in customer_ids:
            cid_str = str(cid).strip()
            if not cid_str:
                continue

            recorder_params = {
                "customer_id": cid_str,
                "segment_id": seg_id,
                "tag": audience_tag,
            }

            try:
                result = router.execute(
                    capability,
                    {"id": cid_str, "tags": [audience_tag]},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "apply_audience_tags raised for %s: %s",
                    cid_str, exc,
                )
                record_writeback(
                    engine="audience_targeting",
                    action_type="apply_audience_tags",
                    capability="SHOPIFY_TAG_CUSTOMER",
                    params=recorder_params,
                    success=False,
                    error=f"adapter_raised: {exc}",
                )
                results.append({
                    "customer_id": cid_str, "segment_id": seg_id,
                    "applied": False,
                    "error": f"adapter_raised: {exc}",
                })
                continue

            if not getattr(result, "ok", False):
                err = getattr(result, "error", "unknown")
                logger.debug(
                    "apply_audience_tags failed for %s: %s",
                    cid_str, err,
                )
                record_writeback(
                    engine="audience_targeting",
                    action_type="apply_audience_tags",
                    capability="SHOPIFY_TAG_CUSTOMER",
                    params=recorder_params,
                    success=False,
                    error=f"adapter_failed: {err}",
                )
                results.append({
                    "customer_id": cid_str, "segment_id": seg_id,
                    "applied": False,
                    "error": f"adapter_failed: {err}",
                })
                continue

            record_writeback(
                engine="audience_targeting",
                action_type="apply_audience_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=True,
            )
            results.append({
                "customer_id": cid_str, "segment_id": seg_id,
                "applied": True, "error": None,
            })

    return results


# -- Helpers ---------------------------------------------------


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "audience_targeting tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "audience_targeting tag_applier capability lookup raised: %s",
            exc,
        )
        return None
