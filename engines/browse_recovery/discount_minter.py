"""Browse Recovery Engine — Shopify discount-code minter.

The offer_builder produces N personalized offers (one per browsing
user that abandoned), each carrying a ``discount_pct`` recommendation.
Without this stage, those recommendations are inert — the email /
push / retarget-ad copy says "20% off!" while no real code exists in
Shopify, so the merchant has to manually mint codes to honor the
offers.

This module bridges the gap: for each offer above the
``min_intent_likelihood`` cutoff, it calls
``Capability.SHOPIFY_CREATE_DISCOUNT`` via the SmartRouter and stamps
the minted code back onto the offer dict. Below the cutoff (default:
``low``-intent abandoners) we skip — those offers usually go out as
generic "come back" messages that don't need a real discount, and
minting one code per browser at scale would clutter the merchant's
discount list.

Differs from ``cart_recovery/discount_minter`` in shape:

  * cart_recovery: 1 customer → 1 code (returns a single dict).
  * browse_recovery: N users → N codes (mutates each offer in
    place to add ``code`` / ``discount_id`` / ``ends_at`` /
    ``minted``).

Pattern matches cart_recovery's graceful-fallback contract — router
unavailable / non-mintable / failure is logged at debug and the
offer keeps its discount_pct + an empty ``code: ""`` so downstream
consumers can detect "this offer has no real code".

Code naming and bounds (mirrors cart_recovery for consistency):

  * Code name: ``BROWSE-{user-token}-{epoch}`` (≤32 chars).
  * 7-day expiry default; store-level override via
    ``recovery_code_ttl_days`` (clamped 1-90).
  * usage_limit=1, applies_once_per_customer=True so codes can't
    be shared / replayed.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.logger import get_logger

logger = get_logger("browse_recovery.discount_minter")


_DEFAULT_TTL_DAYS = 7

# Code prefix — distinguishes browse-recovery codes from
# cart-recovery (RECOVER-) and merchant-evergreen codes when the
# operator audits the discount list.
_CODE_PREFIX = "BROWSE"

# Likelihood tiers that warrant minting a real code. "low"-intent
# offers go out as generic come-back messages without a discount
# code (saves on the discount-list churn).
_DEFAULT_MINTABLE_LIKELIHOODS = {"high", "medium"}


def mint_offer_codes(
    offers: list[dict[str, Any]],
    intent_scores: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
    *,
    mintable_likelihoods: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Mint a Shopify discount code per qualifying offer.

    Mutates each offer dict in place to add four fields:

      * ``code``: minted Shopify code name, or ``""`` on skip/fail.
      * ``discount_id``: Shopify GID for the code, or ``""``.
      * ``ends_at``: ISO datetime when the code expires.
      * ``minted``: ``True`` only when a real code was created.

    Args:
        offers: Output of ``build_offers`` — list of per-user
            offer dicts.
        intent_scores: Output of ``score_intent`` — used to read
            ``purchase_likelihood`` so we know which offers are
            worth minting for.
        store: Optional store config; honors
            ``recovery_code_ttl_days``.
        mintable_likelihoods: Override the default
            ``{"high", "medium"}`` filter. Pass ``{"high",
            "medium", "low"}`` to mint for everyone, or a smaller
            set to be more conservative.

    Returns:
        The same offers list (mutated). Returned for chainability.
    """
    if not offers:
        return offers

    target_likelihoods = (
        set(mintable_likelihoods)
        if mintable_likelihoods is not None
        else _DEFAULT_MINTABLE_LIKELIHOODS
    )

    likelihood_by_user = _index_likelihoods(intent_scores)

    router = _get_router()
    capability = _get_capability_create_discount()
    if router is None or capability is None:
        # Router not initialised → stamp empty code fields on every
        # offer so downstream contract is consistent.
        for offer in offers:
            _stamp_skipped(offer)
        return offers

    ttl_days = _resolve_ttl_days(store)

    for offer in offers:
        user_id = str(offer.get("user_id", ""))
        likelihood = likelihood_by_user.get(user_id, "low")
        if likelihood not in target_likelihoods:
            _stamp_skipped(offer)
            continue

        try:
            discount_pct = float(offer.get("discount_pct", 0))
        except (TypeError, ValueError):
            _stamp_skipped(offer)
            continue
        if discount_pct <= 0:
            _stamp_skipped(offer)
            continue

        code_name = _build_code_name(user_id)
        starts_at = datetime.now(timezone.utc)
        ends_at = starts_at + timedelta(days=ttl_days)
        params: dict[str, Any] = {
            "title": (
                f"Browse recovery: {discount_pct:g}% off "
                f"({likelihood} intent)"
            ),
            "code": code_name,
            "starts_at": starts_at.replace(microsecond=0).isoformat()
                .replace("+00:00", "Z"),
            "ends_at": ends_at.replace(microsecond=0).isoformat()
                .replace("+00:00", "Z"),
            "percentage": discount_pct,
            "usage_limit": 1,
            "applies_once_per_customer": True,
        }

        try:
            result = router.execute(capability, params)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "browse-recovery mint raised for %s: %s",
                user_id, exc,
            )
            _stamp_skipped(offer)
            continue

        if not getattr(result, "ok", False):
            logger.debug(
                "browse-recovery mint failed for %s: %s",
                user_id, getattr(result, "error", "unknown"),
            )
            _stamp_skipped(offer)
            continue

        data = getattr(result, "data", {}) or {}
        offer["code"] = code_name
        offer["discount_id"] = (
            data.get("discount_id") or data.get("id") or ""
        )
        offer["ends_at"] = params["ends_at"]
        offer["minted"] = True

    return offers


# ── Helpers ────────────────────────────────────────────────────


def _index_likelihoods(
    intent_scores: list[dict[str, Any]],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in intent_scores or []:
        if not isinstance(s, dict):
            continue
        uid = str(s.get("user_id", ""))
        if not uid:
            continue
        out[uid] = str(s.get("purchase_likelihood", "low"))
    return out


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


def _stamp_skipped(offer: dict[str, Any]) -> None:
    offer["code"] = ""
    offer["discount_id"] = ""
    offer["ends_at"] = ""
    offer["minted"] = False


def _build_code_name(user_id: str) -> str:
    """Generate ``BROWSE-{token}-{epoch}`` (≤32 chars).

    Token is the user_id with non-alphanumerics stripped, uppercased,
    capped at 12 chars. Falls back to ``ANON`` for blanks.
    """
    token = "ANON"
    if user_id:
        sanitized = "".join(
            c for c in user_id.upper() if c.isalnum()
        )
        if sanitized:
            token = sanitized[:12]
    epoch = int(time.time())
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
