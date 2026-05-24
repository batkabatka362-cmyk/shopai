"""Customer Journey Engine -- journey-stage tag applier.

Bridges the engine's ``customer_journeys`` list into Shopify
CUSTOMER tag updates. Each customer gets tagged with their
furthest reached journey stage so marketing engines can
segment by funnel position.

Tag format:
  * ``journey:awareness``     -- top of funnel (page_view, ad_click)
  * ``journey:consideration`` -- considering (product_view, add_to_cart)
  * ``journey:purchase``      -- bought (checkout_start, order_complete)
  * ``journey:retention``     -- repeat / subscriber / referrer / reviewer

Customers with ``furthest_stage="none"`` (no engagement signal)
silently skipped. Uses SHOPIFY_TAG_CUSTOMER (additive) so no
read-merge-write dance, same shape as cohort_analysis applier.

Second customer-tag wireup (after cohort_analysis). Records via
Pattern Z so journey-tagging fans into the learning loop.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.customer_journey.tag_applier")


_VALID_STAGES = {"awareness", "consideration", "purchase", "retention"}


def apply_journey_tags(
    customer_journeys: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag every customer with their furthest journey stage.

    Args:
        customer_journeys: From ``CustomerJourneyEngine.run()``'s
            ``build_result.customer_journeys`` (NOT in the public
            output -- callers grab it pre-aggregate). Each carries
            ``customer_id`` + ``furthest_stage``.

    Returns:
        Per-customer results list with ``{customer_id, stage,
        applied, error}``.
    """
    if not isinstance(customer_journeys, list) or not customer_journeys:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "customer_id": str(j.get("customer_id", "")),
                "stage": str(j.get("furthest_stage", "")),
                "applied": False,
                "error": "router_unavailable",
            }
            for j in customer_journeys
            if isinstance(j, dict)
            and j.get("customer_id")
            and j.get("furthest_stage") in _VALID_STAGES
        ]

    results: list[dict[str, Any]] = []
    for journey in customer_journeys:
        if not isinstance(journey, dict):
            continue
        cid = str(journey.get("customer_id", "")).strip()
        stage = str(journey.get("furthest_stage", "")).strip()
        if not cid or stage not in _VALID_STAGES:
            continue

        journey_tag = f"journey:{stage}"
        recorder_params = {
            "customer_id": cid,
            "stage": stage,
            "tag": journey_tag,
        }

        try:
            result = router.execute(
                capability,
                {"id": cid, "tags": [journey_tag]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_journey_tags raised for %s: %s", cid, exc,
            )
            record_writeback(
                engine="customer_journey",
                action_type="apply_journey_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "customer_id": cid, "stage": stage,
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_journey_tags failed for %s: %s", cid, err,
            )
            record_writeback(
                engine="customer_journey",
                action_type="apply_journey_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "customer_id": cid, "stage": stage,
                "applied": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="customer_journey",
            action_type="apply_journey_tags",
            capability="SHOPIFY_TAG_CUSTOMER",
            params=recorder_params,
            success=True,
        )
        results.append({
            "customer_id": cid, "stage": stage,
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
            "customer_journey tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "customer_journey tag_applier capability lookup raised: %s",
            exc,
        )
        return None
