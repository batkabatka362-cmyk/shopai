"""Loyalty Engine — Shopify discount-code minter.

Bridges the engine's calculated tier-reward into a real Shopify
discount code. Thin wrapper around
``engines._recovery_codes.mint_recovery_code``: this module owns
the per-engine logic (parsing percentage from the human-readable
reward string, building per-customer tokens, resolving TTL), the
shared core handles the actual SmartRouter call.

Without this stage, the loyalty engine recommends "10% off next
order" for a Silver-tier customer but no actual discount code
exists in Shopify — the merchant has to mint one manually before
the customer can redeem.

Returns ``None`` (so the pipeline keeps running with no minted
code) when the reward isn't a discount type, the percentage can't
be parsed, the router is unavailable, or the adapter call fails.
"""
from __future__ import annotations

import re
from typing import Any

from engines._recovery_codes import mint_recovery_code as _mint
from engines._writeback_recorder import record_writeback


# Code-name prefix. Distinguishes loyalty rewards from recovery
# codes / operator evergreen codes when the merchant audits the
# discount list.
_CODE_PREFIX = "LOYALTY"

# Default code TTL when the program config doesn't specify one.
# Longer than recovery codes (7 days) because loyalty rewards are
# expected to be redeemed at a leisurely pace, not in response
# to an active funnel.
_DEFAULT_TTL_DAYS = 30


def mint_loyalty_code(
    customer_id: str,
    reward: dict[str, Any],
    program_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a one-shot Shopify discount code for a tier reward.

    Args:
        customer_id: Shopify customer GID (used for the code
            suffix so each loyalty code is unique per customer).
        reward: Reward dict from reward_recommender — carries
            ``reward`` (human-readable string like "10% off next
            order"), ``points_cost``, and ``type``.
        program_config: Optional program config — looks for
            ``loyalty_code_ttl_days`` to override the 30-day default.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}`` on
        success, or ``None`` if the reward isn't a percentage
        discount, the percentage can't be parsed, or the adapter
        call fails.
    """
    reward_type = str(reward.get("type", "")).lower()
    if reward_type != "discount":
        return None

    percentage = _parse_percentage(reward.get("reward", ""))
    if percentage is None or percentage <= 0:
        return None

    token = _build_token(customer_id)
    ttl_days = _resolve_ttl_days(program_config)

    title = (
        f"Loyalty reward: {percentage:g}% off"
    )

    minted = _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=percentage,
        value_kind="percentage",
        ttl_days=ttl_days,
        title=title,
    )

    # Phase 8: feed the autonomous learning loop so the system
    # can later correlate minted loyalty codes with redemption.
    record_writeback(
        engine="loyalty",
        action_type="mint_loyalty_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params={
            "customer_id": customer_id,
            "percentage": percentage,
            "ttl_days": ttl_days,
        },
        success=minted is not None,
        error=None if minted is not None else "mint_returned_none",
    )

    return minted


# ── Per-engine helpers ────────────────────────────────────────


_PERCENTAGE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _parse_percentage(reward_text: Any) -> float | None:
    """Extract the percentage from strings like "10% off next order".

    Returns the float value (e.g. 10.0) on success, or ``None``
    when no percentage is present (free shipping, access perks,
    etc — those aren't mintable as discount codes).
    """
    if not isinstance(reward_text, str):
        return None
    match = _PERCENTAGE_PATTERN.search(reward_text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _build_token(customer_id: Any) -> str:
    """Derive a unique-per-customer token for the code suffix.

    Format priority:
      1. Numeric id from customer GID
      2. Sanitised raw string (uppercased, capped at 12 chars)
      3. ``ANON``
    """
    if isinstance(customer_id, str) and customer_id.strip():
        # GID like "gid://shopify/Customer/12345" → "12345"
        token = customer_id.rstrip("/").rsplit("/", 1)[-1] or "ANON"
        # Sanitise to alphanumeric + cap length so the resulting
        # discount code stays well under Shopify's 32-char limit.
        token = "".join(c for c in token if c.isalnum()).upper()[:12]
        if token:
            return token
    return "ANON"


def _resolve_ttl_days(program_config: dict[str, Any] | None) -> int:
    if not isinstance(program_config, dict):
        return _DEFAULT_TTL_DAYS
    raw = program_config.get("loyalty_code_ttl_days")
    if raw is None:
        return _DEFAULT_TTL_DAYS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
