"""Subscription Engine -- churn-risk tag applier.

Bridges the engine's ``churn_risks`` list into Shopify
CUSTOMER tag updates. Subscribers at high or medium churn
risk get tagged so retention campaigns can target them
without re-running churn prediction.

Tag format:
  * ``subscription:churn_high``   -- risk_level = high (>=0.6)
  * ``subscription:churn_medium`` -- risk_level = medium (>=0.3)

Subscribers at "low" or "minimal" risk silently skipped --
they're not at risk yet and don't warrant retention spend.

Fourth customer-tag wireup (cohort_analysis, customer_journey,
audience_targeting were first three). Uses SHOPIFY_TAG_CUSTOMER
(additive). Records via Pattern Z.

Assumes ``subscriber_id`` is a Shopify customer GID. If a
store's subscription provider uses a different id space, the
tag won't resolve to a Shopify customer and the API will
return an error (recorded as failure via Pattern Z).
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.subscription.tag_applier")


_TAGGABLE_LEVELS = {"high", "medium"}


def apply_churn_risk_tags(
    churn_risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tag subscribers with their churn-risk level.

    Args:
        churn_risks: From ``SubscriptionEngine.run()``'s
            ``data.churn_risks``. Each carries ``subscriber_id``
            + ``risk_level``.

    Returns:
        Per-subscriber results with ``{subscriber_id, risk_level,
        applied, error}``.
    """
    if not isinstance(churn_risks, list) or not churn_risks:
        return []

    # Filter once
    eligible = [
        r for r in churn_risks
        if isinstance(r, dict)
        and str(r.get("subscriber_id", "")).strip()
        and str(r.get("risk_level", "")).lower() in _TAGGABLE_LEVELS
    ]
    if not eligible:
        return []

    router = _get_router()
    capability = _get_capability_tag_customer()
    if router is None or capability is None:
        return [
            {
                "subscriber_id": str(r.get("subscriber_id", "")),
                "risk_level": str(r.get("risk_level", "")),
                "applied": False,
                "error": "router_unavailable",
            }
            for r in eligible
        ]

    results: list[dict[str, Any]] = []
    for risk in eligible:
        sid = str(risk.get("subscriber_id", "")).strip()
        level = str(risk.get("risk_level", "")).lower()
        churn_tag = f"subscription:churn_{level}"

        recorder_params = {
            "subscriber_id": sid,
            "risk_level": level,
            "tag": churn_tag,
        }

        try:
            result = router.execute(
                capability,
                {"id": sid, "tags": [churn_tag]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "apply_churn_risk_tags raised for %s: %s", sid, exc,
            )
            record_writeback(
                engine="subscription",
                action_type="apply_churn_risk_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_raised: {exc}",
            )
            results.append({
                "subscriber_id": sid, "risk_level": level,
                "applied": False,
                "error": f"adapter_raised: {exc}",
            })
            continue

        if not getattr(result, "ok", False):
            err = getattr(result, "error", "unknown")
            logger.debug(
                "apply_churn_risk_tags failed for %s: %s", sid, err,
            )
            record_writeback(
                engine="subscription",
                action_type="apply_churn_risk_tags",
                capability="SHOPIFY_TAG_CUSTOMER",
                params=recorder_params,
                success=False,
                error=f"adapter_failed: {err}",
            )
            results.append({
                "subscriber_id": sid, "risk_level": level,
                "applied": False,
                "error": f"adapter_failed: {err}",
            })
            continue

        record_writeback(
            engine="subscription",
            action_type="apply_churn_risk_tags",
            capability="SHOPIFY_TAG_CUSTOMER",
            params=recorder_params,
            success=True,
        )
        results.append({
            "subscriber_id": sid, "risk_level": level,
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
            "subscription tag_applier router lookup raised: %s", exc,
        )
        return None


def _get_capability_tag_customer() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_CUSTOMER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "subscription tag_applier capability lookup raised: %s",
            exc,
        )
        return None
