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

import os
import re
from typing import Any

from engines._agi_context import (
    capture_decision_context,
    explain_thrash_block,
    should_block_thrashing_store,
)
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

# AGI Phase 2 v2 wiring: minimum similar-decisions count required
# before the guardrail will block. Lower than this and we don't
# have enough signal to refuse the mint -- the captured context
# is too sparse to be statistically meaningful.
_AGI_GUARDRAIL_MIN_SIMILAR = 3


def _agi_guardrail_enabled() -> bool:
    """Opt-in guardrail: only blocks when the operator sets
    ``SHOPAI_LOYALTY_AGI_GUARDRAIL=1``.

    Default OFF preserves v1 behaviour (observational capture).
    Opt-in flips to v2: the engine actually REFUSES to mint when
    the captured AGI signal indicates strong past failure.
    """
    return os.environ.get("SHOPAI_LOYALTY_AGI_GUARDRAIL", "") in {
        "1", "true", "yes", "on",
    }


def _should_block_mint(metrics: dict[str, Any] | None) -> bool:
    """Conservative guardrail: block ONLY when the signal is
    unambiguous.

    Three conditions ALL must hold:
      1. At least ``_AGI_GUARDRAIL_MIN_SIMILAR`` similar past
         decisions exist (sparse signal isn't actionable).
      2. At least one had a negative outcome.
      3. ZERO had positive outcomes (mixed signal still gets a
         chance -- only unmixed-negative gets blocked).

    This is intentionally strict. False negatives (allow when
    we should block) are preferable to false positives (block a
    customer mint when we shouldn't) -- a refused mint = lost
    revenue. The guardrail's job is "kill obviously bad mints",
    not "kill any mint with mixed history".
    """
    if not metrics:
        return False
    if int(metrics.get("similar_count", 0) or 0) < _AGI_GUARDRAIL_MIN_SIMILAR:
        return False
    if not metrics.get("recent_negative", False):
        return False
    if metrics.get("recent_positive", False):
        # Mixed signal -- don't block.
        return False
    return True


def _explain_block(metrics: dict[str, Any]) -> str:
    """One-line reason string for ``record_writeback``'s error
    field when the guardrail blocks a mint."""
    return (
        f"agi_guardrail_blocked: "
        f"similar={metrics.get('similar_count', 0)} "
        f"negative=true positive=false "
        f"avg_relevance={metrics.get('avg_relevance', 0.0):.2f}"
    )


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

    mint_params = {
        "customer_id": customer_id,
        "percentage": percentage,
        "ttl_days": ttl_days,
    }

    # AGI Phase 2: capture the snapshot + retrieval context. The
    # captured signal is always written into ``record_writeback``
    # so operators can see what context the engine had at mint
    # time, regardless of whether the guardrail kicks in.
    agi_context = capture_decision_context(
        engine="loyalty",
        action_type="mint_loyalty_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
    )

    # Wave 917: thrash guardrail. System-level kill switch
    # (env: SHOPAI_THRASH_GUARDRAIL=1). When enabled AND the
    # active store's verdict is thrashing, refuse the mint
    # regardless of per-engine AGI metrics. Decoupled from
    # the AGI guardrail below so operators can flip thrash
    # response without touching per-engine env vars.
    try:
        from core.context import get_active_store_id
        active_store_id = get_active_store_id()
    except Exception:  # noqa: BLE001
        active_store_id = None
    if should_block_thrashing_store(active_store_id):
        record_writeback(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=mint_params,
            success=False,
            error=explain_thrash_block(active_store_id),
            metrics=None,
        )
        return None

    # AGI Phase 2 v2: guardrail. When opted in (via env var) AND
    # the signal is unambiguously negative, REFUSE to mint and
    # record the refusal. The captured metrics make the audit
    # trail explicit -- engineers can see exactly which past
    # actions caused the block.
    agi_metrics = agi_context.get("metrics") or {}
    if _agi_guardrail_enabled() and _should_block_mint(agi_metrics):
        block_reason = _explain_block(agi_metrics)
        record_writeback(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=mint_params,
            success=False,
            error=block_reason,
            metrics=agi_metrics,
        )
        return None

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
    # Metrics passthrough carries the AGI context so the data
    # architecture + learning loop see the same signal the engine
    # had at decision time.
    record_writeback(
        engine="loyalty",
        action_type="mint_loyalty_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
        success=minted is not None,
        error=None if minted is not None else "mint_returned_none",
        metrics=agi_metrics or None,
    )

    return minted


def enqueue_loyalty_for_approval(
    customer_id: str,
    reward: dict[str, Any],
    program_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Park a per-customer loyalty code proposal in the approval queue.

    Same input shape and same upfront guardrails as
    :func:`mint_loyalty_code`. Picked over the direct mint when the
    flow sees ``data.require_approval == True``. No Shopify
    mutation runs; the proposal lands in ``core.approval`` for
    human review and the executor (follow-up PR) replays it on
    approval.

    Returns:
        ``{"pending_action_id", "narrative", "params"}`` once
        queued, or ``None`` when the same upfront guardrails
        (non-discount type / unparseable percentage / queue write
        failure) reject the proposal.
    """
    reward_type = str(reward.get("type", "")).lower()
    if reward_type != "discount":
        return None

    percentage = _parse_percentage(reward.get("reward", ""))
    if percentage is None or percentage <= 0:
        return None

    ttl_days = _resolve_ttl_days(program_config)
    reward_text = str(reward.get("reward", ""))
    narrative = (
        f"Loyalty {percentage:g}% off code for customer "
        f"{customer_id} — {ttl_days}d TTL ({reward_text})"
    )
    params = {
        "customer_id": customer_id,
        "percentage": percentage,
        "ttl_days": ttl_days,
        "reward_text": reward_text,
    }

    try:
        from core.approval import get_approval_queue
        action = get_approval_queue().enqueue(
            engine="loyalty",
            action_type="mint_loyalty_code",
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
