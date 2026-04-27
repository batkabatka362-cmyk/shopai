"""Shared recovery-discount minter — extracted from per-engine duplication.

Phase 28.0 (cart_recovery) and 28.1 (browse_recovery) each shipped a
discount-code minter. The two share a core: build a code name, build
the SHOPIFY_CREATE_DISCOUNT params dict, call the router, parse the
response. They differ in shape (1 customer → 1 code vs N users →
N codes), token derivation, and code-name prefix.

This module is the shared core. Per-engine modules stay thin: they
own the token-derivation + filter logic and call ``mint_recovery_code``
for the actual Shopify call.

Public API::

    from engines._recovery_codes import mint_recovery_code

    result = mint_recovery_code(
        token="CUSTOMER12345",        # any alphanum-stripped string
        code_prefix="RECOVER",        # e.g. "RECOVER" / "BROWSE"
        value=15.0,                   # positive number
        value_kind="percentage",      # or "amount"
        ttl_days=7,                   # 1-90 (clamped)
        title="Cart recovery: 15% off",
    )
    # → {"code", "discount_id", "ends_at", "applies_once"} | None

The minted code is always bounded:
  * ``usage_limit = 1`` — dies after redemption.
  * ``applies_once_per_customer = True`` — can't be shared.
  * Time window: now → now + ttl_days, ISO-8601 with ``Z`` suffix.
  * Code name: ``{prefix}-{token}-{epoch}``, capped at 32 chars.

Returns ``None`` (and logs at debug) when the router is unavailable,
the value is non-positive / non-numeric, the value_kind is unknown,
or the adapter call raises / returns ``ok=False``. Callers stamp a
"skipped" reason on their side.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.logger import get_logger

logger = get_logger("engines.recovery_codes")


_DEFAULT_TTL_DAYS = 7
_MIN_TTL_DAYS = 1
_MAX_TTL_DAYS = 90

_VALID_VALUE_KINDS = {"percentage", "amount"}


def mint_recovery_code(
    *,
    token: str,
    code_prefix: str,
    value: Any,
    value_kind: str,
    ttl_days: int = _DEFAULT_TTL_DAYS,
    title: str | None = None,
    usage_limit: int | None = 1,
    applies_once_per_customer: bool = True,
) -> dict[str, Any] | None:
    """Mint a one-shot Shopify discount code via the SmartRouter.

    Args:
        token: User/customer-derived suffix (e.g. ``"CUSTOMER12345"``,
            ``"USERHIGH"``). Combined with ``code_prefix`` + epoch
            into the code name.
        code_prefix: Operator-facing label distinguishing this
            minter's codes (e.g. ``"RECOVER"`` for cart recovery,
            ``"BROWSE"`` for browse recovery).
        value: The discount magnitude. Numeric (int / float / numeric
            string). Non-positive / non-numeric → ``None``.
        value_kind: Either ``"percentage"`` or ``"amount"``. Routes
            the value to the right ``percentage`` / ``amount`` field
            on the adapter call.
        ttl_days: Days the code is valid. Clamped to [1, 90].
        title: Operator-facing label shown in the discount list.
            Auto-generated from ``code_prefix`` + ``value`` if None.
        usage_limit: Max total redemptions across all customers.
            Defaults to 1 (one-shot). Pass ``None`` for unlimited
            (storewide promo codes).
        applies_once_per_customer: When True, each customer can
            only redeem once. Defaults to True (recovery semantics).
            Pass False for evergreen promo codes that customers
            should be able to use repeatedly.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}`` on
        success, or ``None`` on any failure mode.
    """
    kind = (value_kind or "").strip().lower()
    if kind not in _VALID_VALUE_KINDS:
        return None

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    router = _get_router()
    capability = _get_capability_create_discount()
    if router is None or capability is None:
        return None

    code_name = _build_code_name(code_prefix, token)
    starts_at = datetime.now(timezone.utc)
    ends_at = starts_at + timedelta(days=_clamp_ttl(ttl_days))

    if title is None:
        if kind == "percentage":
            title = f"{code_prefix} {amount:g}% off"
        else:
            title = f"{code_prefix} {amount:g} off"

    params: dict[str, Any] = {
        "title": title,
        "code": code_name,
        "starts_at": starts_at.replace(microsecond=0).isoformat()
            .replace("+00:00", "Z"),
        "ends_at": ends_at.replace(microsecond=0).isoformat()
            .replace("+00:00", "Z"),
        "applies_once_per_customer": bool(applies_once_per_customer),
    }
    if usage_limit is not None:
        try:
            params["usage_limit"] = max(1, int(usage_limit))
        except (TypeError, ValueError):
            params["usage_limit"] = 1
    if kind == "percentage":
        params["percentage"] = amount
    else:
        params["amount"] = amount

    try:
        result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "%s mint raised: %s", code_prefix, exc,
        )
        return None

    if not getattr(result, "ok", False):
        logger.debug(
            "%s mint failed: %s",
            code_prefix, getattr(result, "error", "unknown"),
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
        "applies_once": bool(applies_once_per_customer),
    }


# ── Helpers ────────────────────────────────────────────────────


def _build_code_name(prefix: str, token: str) -> str:
    """Generate ``{prefix}-{token}-{epoch}`` (≤32 chars).

    Token defaults to ``ANON`` for blanks. Prefix is upper-cased.
    """
    safe_prefix = (prefix or "REC").strip().upper() or "REC"
    safe_token = (token or "").strip() or "ANON"
    epoch = int(time.time())
    return f"{safe_prefix}-{safe_token}-{epoch}"[:32]


def _clamp_ttl(raw: Any) -> int:
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    return max(_MIN_TTL_DAYS, min(days, _MAX_TTL_DAYS))


def _get_router() -> Any | None:
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
