"""Discount Strategy Engine — Shopify discount-code minter.

Bridges the engine's calculated storewide strategy into a real
Shopify discount code. Thin wrapper around
``engines._recovery_codes.mint_recovery_code``: this module owns
the per-engine logic (filtering by strategy type, converting
``depth_pct`` 0-1 fraction to 0-100 percentage, mapping
``duration_hours`` to TTL days, deriving a deterministic token,
applying safety guardrails), the shared core handles the actual
SmartRouter call.

Without this stage, the discount-strategy engine recommends "15%
off, 24 hours, all customers" but no actual storewide promo code
exists in Shopify — the merchant has to mint one manually.

Returns ``None`` (so the pipeline keeps running with no minted
code) when:

  * The strategy type isn't ``percentage_off`` (other types like
    ``bogo`` / ``free_shipping`` need different mutations).
  * ``depth_pct`` is non-positive.
  * ``cannibalization_risk == "high"`` (don't auto-apply
    high-risk strategies; human approval required).
  * The router is unavailable / adapter call fails.

Unlike loyalty / cart_recovery codes, the storewide promo code is:

  * Multi-use (``usage_limit=None`` → unlimited).
  * Reusable per customer (``applies_once_per_customer=False``).
  * Audience-scoped only via the title / token suffix; deeper
    audience targeting (Plus segments, customer tags) is left
    for a follow-up adapter wire-up.
"""
from __future__ import annotations

from typing import Any

from engines._recovery_codes import mint_recovery_code as _mint


# Code-name prefix. Distinguishes storewide promos from
# per-customer recovery / loyalty codes.
_CODE_PREFIX = "PROMO"

# Default TTL fallback when duration_hours can't be parsed.
_DEFAULT_TTL_DAYS = 7

# Strategy types that map to a percentage discount code.
# Other types (``free_shipping``, ``bogo``, ``dollar_off``,
# ``bundle``) need separate adapter capabilities and aren't in
# scope for this minter.
_MINTABLE_TYPES = {"percentage_off"}

# Cannibalization risk levels we won't auto-apply.
_BLOCKED_RISKS = {"high"}


def mint_strategy_code(
    strategy: dict[str, Any],
    cannibalization_risk: str = "",
    confidence: float = 0.0,
    *,
    min_confidence: float = 0.0,
) -> dict[str, Any] | None:
    """Mint a storewide promo code matching the calculated strategy.

    Args:
        strategy: Strategy dict from the discount_strategy engine
            with ``type``, ``depth_pct``, ``target_audience``,
            ``duration_hours``, ``start_time``.
        cannibalization_risk: Risk classification from the
            cannibalization checker (``"low"`` / ``"medium"`` /
            ``"high"``). The minter blocks on ``"high"``.
        confidence: Projection confidence 0.0-1.0 from the
            revenue projector. The minter blocks below
            ``min_confidence``.
        min_confidence: Floor for the confidence guardrail.
            Default 0.0 (any confidence acceptable). Callers
            wanting stricter gating pass e.g. ``0.6``.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once"}`` on
        success, or ``None`` if the strategy isn't mintable, the
        guardrail blocked, or the adapter call failed. On block,
        the engine output keeps the recommendation but no code is
        created.
    """
    strategy_type = str(strategy.get("type", "")).lower()
    if strategy_type not in _MINTABLE_TYPES:
        return None

    if str(cannibalization_risk).lower() in _BLOCKED_RISKS:
        return None

    if float(confidence or 0.0) < float(min_confidence or 0.0):
        return None

    percentage = _depth_to_percentage(strategy.get("depth_pct"))
    if percentage is None or percentage <= 0:
        return None

    audience = str(strategy.get("target_audience", "all")).strip()
    token = _build_token(audience)
    ttl_days = _hours_to_ttl_days(strategy.get("duration_hours"))

    title = f"Storewide promo: {percentage:g}% off ({audience})"

    return _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=percentage,
        value_kind="percentage",
        ttl_days=ttl_days,
        title=title,
        # Storewide codes — multi-use, customers reuse.
        usage_limit=None,
        applies_once_per_customer=False,
    )


# ── Per-engine helpers ────────────────────────────────────────


def _depth_to_percentage(raw: Any) -> float | None:
    """Convert ``depth_pct`` (0-1 fraction) to 0-100 percentage.

    The engine emits 0.15 for "15% off"; Shopify's discount API
    expects 15.0. Returns ``None`` for unparseable / out-of-range
    inputs.
    """
    try:
        depth = float(raw)
    except (TypeError, ValueError):
        return None
    if depth <= 0 or depth > 1.0:
        # ``depth_pct`` is a fraction; values >1 are likely a
        # caller passing 15 instead of 0.15. Reject rather than
        # mint a 1500% discount.
        return None
    return round(depth * 100.0, 4)


def _hours_to_ttl_days(raw: Any) -> int:
    """Map ``duration_hours`` (engine output) to TTL days.

    Round up so a 6-hour flash sale still gets a full day of
    code validity (the merchant sets the actual end time on
    their side via the strategy.start_time + duration).
    """
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    if hours <= 0:
        return _DEFAULT_TTL_DAYS
    days = int(hours // 24)
    if hours % 24 > 0:
        days += 1
    # Shared core clamps to [1, 90] anyway.
    return max(1, days)


def _build_token(audience: str) -> str:
    """Build a token from the audience descriptor.

    ``"all"`` → ``"ALL"``
    ``"vip-tier"`` → ``"VIPTIER"``
    blank → ``"ALL"``
    """
    cleaned = "".join(
        c for c in (audience or "") if c.isalnum()
    ).upper()[:12]
    return cleaned or "ALL"
