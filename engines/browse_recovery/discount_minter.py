"""Browse Recovery Engine — Shopify discount-code minter.

The offer_builder produces N personalized offers (one per browsing
user that abandoned), each carrying a ``discount_pct`` recommendation.
Without this stage, those recommendations are inert: the email /
push / retarget-ad copy says "20% off!" while no real code exists.

This module bridges the gap: for each offer above the
``mintable_likelihoods`` cutoff, calls
``engines._recovery_codes.mint_recovery_code`` and stamps the result
back onto the offer dict in place. Below the cutoff we skip — those
offers usually go out as generic come-back messages without a code,
and minting per-browser at scale would clutter the merchant's
discount list.

Differs from cart_recovery's minter in shape:

  * cart_recovery: 1 customer → 1 code (returns a dict).
  * browse_recovery: N users → N codes (mutates each offer in
    place to add ``code`` / ``discount_id`` / ``ends_at`` /
    ``minted``).

Pattern matches cart_recovery's graceful-fallback contract — every
failure mode (router unavailable / non-mintable / adapter raises /
adapter ok=False / out-of-filter / zero-pct) stamps the offer with
empty code fields + ``minted=False`` so downstream consumers can
detect "no real code, send a generic come-back message".
"""
from __future__ import annotations

from typing import Any

from engines._agi_context import capture_decision_context
from engines._recovery_codes import mint_recovery_code as _mint
from engines._writeback_recorder import record_writeback


# Code prefix — distinguishes browse-recovery codes from
# cart-recovery (RECOVER-) and merchant-evergreen codes.
_CODE_PREFIX = "BROWSE"

_DEFAULT_TTL_DAYS = 7

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

    Mutates each offer dict in place with four fields:
      * ``code``: minted code name, or ``""`` on skip/fail.
      * ``discount_id``: Shopify GID, or ``""``.
      * ``ends_at``: ISO datetime, or ``""``.
      * ``minted``: ``True`` only when a real code was created.

    Args:
        offers: Output of ``build_offers`` — per-user offer dicts.
        intent_scores: Output of ``score_intent`` — used to read
            ``purchase_likelihood`` per user.
        store: Optional store config; honors
            ``recovery_code_ttl_days``.
        mintable_likelihoods: Override the default ``{"high",
            "medium"}`` filter.

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

        token = _build_token(user_id)
        title = (
            f"Browse recovery: {discount_pct:g}% off "
            f"({likelihood} intent)"
        )
        mint_params = {
            "token": token,
            "value": discount_pct,
            "value_kind": "percentage",
            "ttl_days": ttl_days,
            "likelihood": likelihood,
        }

        # AGI Phase 2: observational context capture (loyalty +
        # cart_recovery reference pattern). Browse_recovery mints
        # one code per offer, so we capture per offer -- gives the
        # learning loop per-likelihood-tier signal.
        agi_context = capture_decision_context(
            engine="browse_recovery",
            action_type="mint_browse_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=mint_params,
        )

        result = _mint(
            token=token,
            code_prefix=_CODE_PREFIX,
            value=discount_pct,
            value_kind="percentage",
            ttl_days=ttl_days,
            title=title,
        )

        # Phase 8: feed the autonomous learning loop so the system
        # can later correlate minted browse-recovery codes with
        # redemption.
        record_writeback(
            engine="browse_recovery",
            action_type="mint_browse_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=mint_params,
            success=result is not None,
            error=(
                None if result is not None else "mint_returned_none"
            ),
            metrics=agi_context.get("metrics") or None,
        )

        if result is None:
            _stamp_skipped(offer)
            continue

        offer["code"] = result["code"]
        offer["discount_id"] = result.get("discount_id", "") or ""
        offer["ends_at"] = result.get("ends_at", "") or ""
        offer["minted"] = True

    return offers


def enqueue_offer_codes_for_approval(
    offers: list[dict[str, Any]],
    intent_scores: list[dict[str, Any]],
    store: dict[str, Any] | None = None,
    *,
    mintable_likelihoods: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Park per-offer code proposals in the approval queue.

    Per-engine alternative to :func:`mint_offer_codes` — selected
    by the flow when ``data.require_approval=True``. Same upfront
    filters (intent likelihood gate + positive discount_pct);
    surviving offers each enqueue one pending action and get
    stamped with ``pending_action_id`` (mutually exclusive with
    the ``minted`` field that the direct path stamps).

    Skipped offers get the same empty-code stamp the direct path
    uses so downstream consumers can keep detecting "no real
    code, send a generic come-back message" via ``minted=False``.

    The function mutates each offer dict in place and returns
    the same list for chain readability — same contract as the
    direct path.
    """
    if not offers:
        return offers

    target_likelihoods = (
        set(mintable_likelihoods)
        if mintable_likelihoods is not None
        else _DEFAULT_MINTABLE_LIKELIHOODS
    )
    likelihood_by_user = _index_likelihoods(intent_scores)
    ttl_days = _resolve_ttl_days(store)

    try:
        from core.approval import get_approval_queue
        queue = get_approval_queue()
    except Exception:  # noqa: BLE001
        for offer in offers:
            _stamp_skipped(offer)
        return offers

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

        token = _build_token(user_id)
        narrative = (
            f"Browse recovery code for user {user_id}: "
            f"{discount_pct:g}% off ({likelihood} intent, "
            f"{ttl_days}d TTL)"
        )
        params = {
            "token": token,
            "value": discount_pct,
            "value_kind": "percentage",
            "ttl_days": ttl_days,
            "user_id": user_id,
            "likelihood": likelihood,
            "code_prefix": _CODE_PREFIX,
        }

        try:
            action = queue.enqueue(
                engine="browse_recovery",
                action_type="mint_browse_recovery_code",
                capability="SHOPIFY_CREATE_DISCOUNT",
                params=params,
                narrative=narrative,
            )
        except Exception:  # noqa: BLE001
            _stamp_skipped(offer)
            continue

        # Mutate in place: minted=False because nothing landed
        # on Shopify yet, but pending_action_id surfaces so the
        # caller can correlate this offer with the queue row
        # once the merchant approves.
        offer["code"] = ""
        offer["discount_id"] = ""
        offer["ends_at"] = ""
        offer["minted"] = False
        offer["pending_action_id"] = action.id

    return offers


# ── Per-engine helpers ────────────────────────────────────────


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


def _stamp_skipped(offer: dict[str, Any]) -> None:
    offer["code"] = ""
    offer["discount_id"] = ""
    offer["ends_at"] = ""
    offer["minted"] = False


def _build_token(user_id: str) -> str:
    """Sanitised user_id, uppercase, alphanum-only, capped at 12.

    Falls back to ``ANON`` for blanks.
    """
    if not user_id:
        return "ANON"
    sanitized = "".join(
        c for c in user_id.upper() if c.isalnum()
    )
    return sanitized[:12] or "ANON"


def _resolve_ttl_days(store: dict[str, Any] | None) -> int:
    if not isinstance(store, dict):
        return _DEFAULT_TTL_DAYS
    raw = store.get("recovery_code_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
