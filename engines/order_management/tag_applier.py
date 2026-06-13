"""Order Management Engine -- fraud-risk order tag applier.

Bridges the engine's fraud-screen output into Shopify ORDER
tag updates. Orders at high or medium fraud risk get tagged
so the operator (or a downstream review queue) can prioritize
manual review.

First ORDER-tag wireup. Earlier appliers tagged products
(SHOPIFY_UPDATE_PRODUCT, merge required) or customers
(SHOPIFY_TAG_CUSTOMER, additive). This one uses
SHOPIFY_TAG_ORDER (additive -- same shape as customer tags).

Tag composition:
  * ``fraud:high_risk`` -- risk_level = high (auto-cancel
    flow already executes if recommendation = reject; this
    catches the cases where recommendation was "review"
    despite high risk)
  * ``fraud:review``    -- risk_level = medium

Low / unknown risk silently skipped (no operator action needed).

Records via Pattern Z so fraud-tagging fans into the learning
loop.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from engines._writeback_recorder import record_writeback

logger = get_logger("engines.order_management.tag_applier")


_HIGH_TAG = "fraud:high_risk"
_MEDIUM_TAG = "fraud:review"


def apply_fraud_tags(
    order_id: str,
    fraud_screen: dict[str, Any],
) -> dict[str, Any]:
    """Tag an order with its fraud-risk level.

    Args:
        order_id: Shopify order GID. Empty -> skipped.
        fraud_screen: ``fraud_screen`` field from engine output
            (carries ``risk_level``).

    Returns:
        Result dict with applied / tag / error.
    """
    oid = str(order_id or "").strip()
    if not oid:
        return _skip_result("", "no_order_id")

    level = str(fraud_screen.get("risk_level", "")).lower()
    tag = _level_to_tag(level)
    if not tag:
        return _skip_result(oid, "low_or_unknown_risk", risk_level=level)

    router = _get_router()
    capability = _get_capability_tag_order()
    if router is None or capability is None:
        return _skip_result(oid, "router_unavailable", risk_level=level)

    recorder_params = {
        "order_id": oid,
        "risk_level": level,
        "tag": tag,
        "recommendation": str(fraud_screen.get("recommendation", "")),
    }

    try:
        result = router.execute(
            capability,
            {"id": oid, "tags": [tag]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "apply_fraud_tags raised for %s: %s", oid, exc,
        )
        record_writeback(
            engine="order_management",
            action_type="apply_fraud_tags",
            capability="SHOPIFY_TAG_ORDER",
            params=recorder_params,
            success=False,
            error=f"adapter_raised: {exc}",
        )
        return {
            "order_id": oid, "applied": False, "tag": tag,
            "risk_level": level,
            "error": f"adapter_raised: {exc}",
        }

    if not getattr(result, "ok", False):
        err = getattr(result, "error", "unknown")
        logger.debug(
            "apply_fraud_tags failed for %s: %s", oid, err,
        )
        record_writeback(
            engine="order_management",
            action_type="apply_fraud_tags",
            capability="SHOPIFY_TAG_ORDER",
            params=recorder_params,
            success=False,
            error=f"adapter_failed: {err}",
        )
        return {
            "order_id": oid, "applied": False, "tag": tag,
            "risk_level": level,
            "error": f"adapter_failed: {err}",
        }

    record_writeback(
        engine="order_management",
        action_type="apply_fraud_tags",
        capability="SHOPIFY_TAG_ORDER",
        params=recorder_params,
        success=True,
    )
    return {
        "order_id": oid, "applied": True, "tag": tag,
        "risk_level": level,
        "error": None,
    }


def _level_to_tag(level: str) -> str:
    return {
        "high": _HIGH_TAG,
        "medium": _MEDIUM_TAG,
    }.get(level, "")


def _skip_result(
    oid: str, error: str, *, risk_level: str = "",
) -> dict[str, Any]:
    return {
        "order_id": oid, "applied": False, "tag": "",
        "risk_level": risk_level,
        "error": error,
    }


# -- Helpers ---------------------------------------------------


def _get_router() -> Any:
    try:
        from core.adapters import get_router
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_management tag_applier router lookup raised: %s",
            exc,
        )
        return None


def _get_capability_tag_order() -> Any:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_TAG_ORDER
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "order_management tag_applier capability lookup raised: %s",
            exc,
        )
        return None
