"""Cart Recovery Engine — Shopify discount-code minter.

Bridges the engine's calculated Incentive into a real Shopify
discount code. Thin wrapper around
``engines._recovery_codes.mint_recovery_code``: this module owns
the per-engine logic (filtering by incentive type, deriving the
customer token, resolving TTL from the store payload), the shared
core handles the actual SmartRouter call.

Without this stage, the cart-recovery email tells the customer "10%
off your cart!" but no actual discount exists in Shopify — the
merchant has to mint one manually before the offer is honored at
checkout.

Returns ``None`` (so the pipeline keeps running with no minted
code) when the router is unavailable, the incentive type isn't
mintable (free_shipping / bundle / loyalty_points / none), the
calculated value is non-positive, or the adapter call fails.
"""
from __future__ import annotations

from typing import Any

from engines._agi_context import capture_decision_context
from engines._recovery_codes import mint_recovery_code as _mint
from engines._writeback_recorder import record_writeback


# Code-name prefix. Distinguishes recovery codes from operator-minted
# evergreen codes when the merchant audits the discount list.
_CODE_PREFIX = "RECOVER"

# Default code TTL when the store payload doesn't specify one.
_DEFAULT_TTL_DAYS = 7

# Incentive types this module knows how to mint. Other types
# (free_shipping, bundle, loyalty_points, none) are out of scope.
_MINTABLE_TYPES = {"percentage", "amount"}


def mint_recovery_code(
    incentive: dict[str, Any],
    customer: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a one-shot Shopify discount code for the calculated
    incentive.

    Args:
        incentive: Incentive dict from incentive_calculator
            (carries ``type`` + ``value``).
        customer: Customer dict — used for the code-name suffix
            so each recovery code is unique per customer.
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

    token = _build_token(customer)
    ttl_days = _resolve_ttl_days(store)
    value = incentive.get("value", 0)

    # Pretty title that mirrors the engine's recommendation copy.
    try:
        amount_for_title = float(value or 0)
    except (TypeError, ValueError):
        amount_for_title = 0.0
    title = (
        f"Cart recovery: {amount_for_title:g}"
        f"{'%' if incentive_type == 'percentage' else ''} off"
    )

    mint_params = {
        "token": token,
        "value": value,
        "value_kind": incentive_type,
        "ttl_days": ttl_days,
    }

    # AGI Phase 2: observational context capture. Same pattern as
    # loyalty's discount_minter -- snapshot + retrieval flow into
    # the writeback recorder so the autonomous loop sees what
    # context the engine had at mint time. v1 is observational
    # (no adjustment of the mint decision based on the signal).
    agi_context = capture_decision_context(
        engine="cart_recovery",
        action_type="mint_cart_recovery_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
    )

    minted = _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=value,
        value_kind=incentive_type,
        ttl_days=ttl_days,
        title=title,
    )

    # Phase 8: feed the autonomous learning loop so the system
    # can later correlate minted recovery codes with redemption.
    # Metrics passthrough carries the AGI context so the data
    # architecture sees the same signal the engine had at decision
    # time (preempts the auto-capture in record_writeback).
    record_writeback(
        engine="cart_recovery",
        action_type="mint_cart_recovery_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
        success=minted is not None,
        error=None if minted is not None else "mint_returned_none",
        metrics=agi_context.get("metrics") or None,
    )
    return minted


def enqueue_recovery_for_approval(
    incentive: dict[str, Any],
    customer: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park a recovery-code proposal in the approval queue.

    Per-engine alternative to :func:`mint_recovery_code` —
    selected by the flow when ``data.require_approval=True``.
    Same upfront filters (must be a percentage/amount incentive,
    positive value); on success returns ``{"pending_action_id",
    "narrative", "params"}`` for the engine output. The merchant's
    approval page sees a single-line summary so they can sanity-
    check before the code lands on Shopify.

    Returns:
        ``{"pending_action_id", "narrative", "params"}`` once
        queued, or ``None`` on guardrail rejection / queue write
        failure — same skip semantics as the direct-mint path.
    """
    incentive_type = str(incentive.get("type", "")).lower()
    if incentive_type not in _MINTABLE_TYPES:
        return None

    try:
        value = float(incentive.get("value", 0) or 0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None

    token = _build_token(customer)
    ttl_days = _resolve_ttl_days(store)

    customer_id = (
        customer.get("id")
        or customer.get("customer_id")
        or customer.get("email")
        or "anon"
    )
    suffix = "% off" if incentive_type == "percentage" else " off"
    narrative = (
        f"Cart recovery code for {customer_id}: "
        f"{value:g}{suffix} ({ttl_days}d TTL)"
    )
    params = {
        "token": token,
        "value": value,
        "value_kind": incentive_type,
        "ttl_days": ttl_days,
        "customer_id": str(customer_id),
        "code_prefix": _CODE_PREFIX,
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="cart_recovery",
            action_type="mint_cart_recovery_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=params,
            narrative=narrative,
        )
    except Exception:  # noqa: BLE001
        return None

    return {
        "pending_action_id": action.id,
        "narrative": narrative,
        "params": params,
    }


# ── Per-engine helpers ────────────────────────────────────────


def _build_token(customer: dict[str, Any]) -> str:
    """Derive a unique-per-customer token for the code suffix.

    Format priority:
      1. Numeric id from customer GID
      2. Sanitised email local-part (uppercased, capped at 12 chars)
      3. ``ANON``
    """
    raw_id = customer.get("id") or customer.get("customer_id")
    if isinstance(raw_id, str) and raw_id.strip():
        # GID like "gid://shopify/Customer/12345" → "12345"
        token = raw_id.rstrip("/").rsplit("/", 1)[-1] or "ANON"
        return token
    email = customer.get("email")
    if isinstance(email, str) and email.strip():
        token = (
            email.split("@", 1)[0].upper()
            .replace(".", "").replace("+", "")[:12]
        )
        if token:
            return token
    return "ANON"


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
