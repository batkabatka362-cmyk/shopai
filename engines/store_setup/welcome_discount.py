"""Auto-generate + apply a welcome discount code at store
launch.

The ``store_design`` engine already produces design hints; the
``discount_strategy`` engine handles ongoing promotional codes
during operations. What was missing: the very first discount
code a store needs the moment it goes live -- a welcome offer
for first-time visitors that converts the "I just landed on
the site" traffic into orders.

This module fills that gap:

  * ``generate_welcome_discount(*, store_name, niche)`` returns
    a discount params dict ready to feed into
    ``SHOPIFY_CREATE_DISCOUNT``. Niche-aware percentages:
      - beauty/fashion -> 15% off (generous, conversion-first)
      - tech/home      -> 10% off (modest, margin-protective)
      - food/general   -> 10% off

  * ``apply_welcome_discount(params, *, store_id)`` pushes the
    params via the EXISTING adapter, records via Pattern Z.

The discount code defaults to ``WELCOME{percentage}`` (e.g.
``WELCOME15``) -- memorable, brandable, and unambiguous to
operators inspecting the store's promo list later.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from engines._writeback_recorder import record_writeback

logger = logging.getLogger(__name__)


# Niche-specific discount percentages -- tuned to balance
# conversion-pull against margin-protection per category.
_NICHE_PERCENTAGES: dict[str, int] = {
    "beauty": 15,
    "fashion": 15,
    "tech": 10,
    "home": 10,
    "food": 10,
    # Pets / fitness / baby: higher discount drives the first
    # bag-of-food / first-supplement-tub / first-onesie
    # repeat-purchase loop -- LTV recovers the up-front
    # margin hit quickly.
    "pets": 15,
    "fitness": 15,
    "baby": 15,
    # Jewelry: tight margin on luxury / mid-range; 10% is the
    # convention for first-purchase nudges without devaluing
    # the brand.
    "jewelry": 10,
    "outdoor": 10,
    "general": 10,
}


def generate_welcome_discount(
    *,
    store_name: str,
    niche: str = "general",
    code: str | None = None,
    usage_limit: int | None = None,
    days_valid: int = 60,
    minimum_subtotal: float | None = None,
) -> dict[str, Any]:
    """Build a discount params dict for a launch welcome code.

    Args:
        store_name: Store display name (returned for context;
            empty string yields an empty dict).
        niche: Lowercase niche key. Unknown niches fall back
            to ``general``.
        code: Override the auto-generated ``WELCOME{N}`` code.
            Trimmed before use; empty/whitespace falls back
            to the default.
        usage_limit: Optional cap on total uses. None = unlimited.
        days_valid: How long the code stays valid from now
            (default 60 days; range 1..365).
        minimum_subtotal: Optional minimum order subtotal in
            store currency. None = no minimum.

    Returns:
        Dict in the friendly call shape of
        ``SHOPIFY_CREATE_DISCOUNT``. Empty dict when store_name
        is blank.
    """
    name = (store_name or "").strip()
    if not name:
        return {}

    niche_n = (niche or "general").strip().lower() or "general"
    pct = _NICHE_PERCENTAGES.get(
        niche_n, _NICHE_PERCENTAGES["general"],
    )

    code_clean = (code or "").strip() or f"WELCOME{pct}"

    days = max(1, min(365, int(days_valid or 60)))
    starts_at = datetime.now(timezone.utc)
    ends_at = starts_at + timedelta(days=days)

    out: dict[str, Any] = {
        "code": code_clean.upper(),
        "title": f"{name} welcome offer",
        "percentage": pct,
        "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at": ends_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if usage_limit is not None and int(usage_limit) > 0:
        out["usage_limit"] = int(usage_limit)
    if (
        minimum_subtotal is not None
        and float(minimum_subtotal) > 0
    ):
        out["minimum_subtotal"] = float(minimum_subtotal)
    return out


def apply_welcome_discount(
    params: dict[str, Any],
    *,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Push a welcome discount via the create-discount adapter.

    Args:
        params: Dict from :func:`generate_welcome_discount`.
            Empty / non-dict input short-circuits.
        store_id: Optional store_id for per-store Pattern Z scope.

    Returns:
        ``{applied, code, percentage, error}`` -- ``applied`` is
        True when the adapter call succeeded.
    """
    if not isinstance(params, dict) or not params:
        return {
            "applied": False,
            "code": None,
            "percentage": None,
            "error": "no_discount_params",
        }

    code = params.get("code")
    percentage = params.get("percentage")

    router = _get_router()
    capability = _get_capability()
    if router is None or capability is None:
        _record(
            code=code, percentage=percentage,
            success=False, store_id=store_id,
            error="router_unavailable",
        )
        return {
            "applied": False,
            "code": code,
            "percentage": percentage,
            "error": "router_unavailable",
        }

    try:
        adapter_result = router.execute(capability, params)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_discount router.execute raised: %s", exc,
        )
        _record(
            code=code, percentage=percentage,
            success=False, store_id=store_id,
            error=str(exc),
        )
        return {
            "applied": False,
            "code": code,
            "percentage": percentage,
            "error": f"adapter_raise: {exc}",
        }

    ok = bool(getattr(adapter_result, "ok", False))
    error = getattr(adapter_result, "error", None)
    if ok:
        _record(
            code=code, percentage=percentage,
            success=True, store_id=store_id,
            error=None,
        )
        return {
            "applied": True,
            "code": code,
            "percentage": percentage,
            "error": None,
        }

    _record(
        code=code, percentage=percentage,
        success=False, store_id=store_id,
        error=str(error or "rejected"),
    )
    return {
        "applied": False,
        "code": code,
        "percentage": percentage,
        "error": str(error or "rejected"),
    }


# --- helpers --------------------------------------------------


def _record(
    *,
    code: Any,
    percentage: Any,
    success: bool,
    store_id: str | None,
    error: str | None,
) -> None:
    params: dict[str, Any] = {
        "code": code,
        "percentage": percentage,
    }
    if store_id:
        params["store_id"] = str(store_id)
    try:
        record_writeback(
            engine="store_setup",
            action_type="apply_welcome_discount",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=params,
            success=bool(success),
            error=error,
            metrics={
                "code": code,
                "percentage": percentage,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_discount record_writeback raised: %s",
            exc,
        )


def _get_router() -> Any | None:
    try:
        from core.adapters import get_router as _get
        return _get()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_discount router import failed: %s", exc,
        )
        return None


def _get_capability() -> Any | None:
    try:
        from core.adapters.base import Capability
        return Capability.SHOPIFY_CREATE_DISCOUNT
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "welcome_discount capability resolve failed: %s",
            exc,
        )
        return None
