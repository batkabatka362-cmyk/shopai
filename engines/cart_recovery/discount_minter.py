"""Cart Recovery Engine — Shopify discount-code minter.

Bridges the engine's calculated Incentive (a recommendation: "offer
10% off, code-named WHATEVER") into a REAL Shopify discount code
the customer can actually redeem.

Without this stage, the cart-recovery email tells the customer "10%
off your cart!" but no actual discount exists in Shopify — the
merchant has to mint one manually before the offer is honored at
checkout. This module closes that loop by calling
``Capability.SHOPIFY_CREATE_DISCOUNT`` via the adapter
``SmartRouter`` whenever the calculated incentive is a percentage or
amount-based discount.

Graceful behavior:

  * Router not initialised → return ``None``. Pipeline continues;
    the email still goes out, but with a placeholder code or the
    merchant's evergreen recovery code (operator's choice).
  * Adapter call raises or returns ``ok=False`` → return ``None``
    with the failure logged. Same downstream behavior.
  * Incentive type is "free_shipping" / "bundle" / "loyalty_points"
    / "none" → return ``None`` (no basic discount needed; free-
    shipping is a separate adapter call out of scope here).

When the call succeeds, returns::

    {
        "code":           "RECOVER-CUSTOMERID-1717372800",
        "discount_id":    "gid://shopify/DiscountCodeNode/123",
        "ends_at":        "2026-04-29T00:00:00Z",
        "applies_once":   True,
    }

The minted code is bounded:
  * 7-day expiry from now (configurable via ``recovery_code_ttl_days``
    on the store payload).
  * ``applies_once_per_customer = True`` so a recovered customer
    can't share the link.
  * ``usage_limit = 1`` so the code dies after redemption.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.logger import get_logger

logger = get_logger("cart_recovery.discount_minter")


# Default code TTL when the store payload doesn't specify one.
_DEFAULT_TTL_DAYS = 7

# Code-name prefix. Distinguishes recovery codes from operator-minted
# evergreen codes when the merchant audits the discount list.
_CODE_PREFIX = "RECOVER"

# Incentive types this module knows how to mint. Other types
# (free_shipping, bundle, loyalty_points, none) are out of scope.
_MINTABLE_TYPES = {"percentage", "amount"}


def mint_recovery_code(
    incentive: dict[str, Any],
    customer: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a real Shopify discount code for the calculated incentive.

    Args:
        incentive: The Incentive dict from the incentive_calculator
            (must carry ``type`` + ``value`` at minimum).
        customer: The customer dict (used for the code-name suffix
            so each recovery code is unique per customer).
        store: Optional store config — looks for
            ``recovery_code_ttl_days`` to override the 7-day default.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}`` on
        success, or ``None`` if the router is unavailable / the
        incentive isn't mintable / the adapter call failed.
    """
    incentive_type = str(incentive.get("type", "")).lower()
    if incentive_type not in _MINTABLE_TYPES:
        return None

    try:
        value = float(incentive.get("value", 0) or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        # Zero-percent / zero-dollar code is a no-op; skip the
        # network call.
        return None

    router = _get_router()
    if router is None:
        return None

    code_name = _build_code_name(customer)
    ttl_days = _resolve_ttl_days(store)
    starts_at = datetime.now(timezone.utc)
    ends_at = starts_at + timedelta(days=ttl_days)
    title = (
        f"Cart recovery: {value:g}"
        f"{'%' if incentive_type == 'percentage' else ''} off"
    )

    params: dict[str, Any] = {
        "title": title,
        "code": code_name,
        "starts_at": starts_at.replace(microsecond=0).isoformat()
            .replace("+00:00", "Z"),
        "ends_at": ends_at.replace(microsecond=0).isoformat()
            .replace("+00:00", "Z"),
        "usage_limit": 1,
        "applies_once_per_customer": True,
    }
    if incentive_type == "percentage":
        params["percentage"] = value
    else:  # amount
        params["amount"] = value

    capability = _get_capability_create_discount()
    if capability is None:
        return None

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug("recovery discount mint raised: %s", exc)
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "recovery discount mint failed: %s",
            getattr(result, "error", "unknown"),
        )
        return None

    data = getattr(result, "data", {}) or {}
    discount_id = (
        data.get("discount_id")
        or data.get("id")
        or ""
    )
    return {
        "code": code_name,
        "discount_id": discount_id,
        "ends_at": params["ends_at"],
        "applies_once": True,
    }


def _get_router() -> Any | None:
    """Lazy router import. Returns ``None`` when the adapter layer
    isn't available."""
    try:
        from core.adapters import get_router
    except Exception as exc:  # noqa: BLE001
        logger.debug("router import failed: %s", exc)
        return None
    try:
        return get_router()
    except Exception as exc:  # noqa: BLE001
        logger.debug("router init failed: %s", exc)
        return None


def _get_capability_create_discount() -> Any | None:
    try:
        from core.adapters.base import Capability
    except Exception as exc:  # noqa: BLE001
        logger.debug("Capability import failed: %s", exc)
        return None
    return Capability.SHOPIFY_CREATE_DISCOUNT


def _build_code_name(customer: dict[str, Any]) -> str:
    """Build a unique recovery code name.

    Format: ``RECOVER-{customer_token}-{epoch}``
    The customer token is the last segment of their GID (numeric id)
    if available, otherwise a hash of the email, otherwise "ANON".
    """
    token = "ANON"
    raw_id = customer.get("id") or customer.get("customer_id")
    if isinstance(raw_id, str) and raw_id.strip():
        # GID like "gid://shopify/Customer/12345" → "12345"
        token = raw_id.rstrip("/").rsplit("/", 1)[-1] or "ANON"
    else:
        email = customer.get("email")
        if isinstance(email, str) and email.strip():
            token = (
                email.split("@", 1)[0].upper()
                .replace(".", "").replace("+", "")[:12]
                or "ANON"
            )
    epoch = int(time.time())
    # Cap total length at ~32 chars so storefronts that display the
    # code in URLs / buttons don't wrap awkwardly.
    return f"{_CODE_PREFIX}-{token}-{epoch}"[:32]


def _resolve_ttl_days(store: dict[str, Any] | None) -> int:
    if not isinstance(store, dict):
        return _DEFAULT_TTL_DAYS
    raw = store.get("recovery_code_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    return max(1, min(days, 90))
