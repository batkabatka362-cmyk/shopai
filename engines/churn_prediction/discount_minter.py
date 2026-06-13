"""Churn Prediction Engine -- Shopify retention-code minter.

Bridges the engine's high-risk churn predictions into real
Shopify discount codes for the "win_back_offer" retention
action. Thin wrapper around
``engines._recovery_codes.mint_recovery_code``: per-engine
logic (filtering by risk level + retention action +
cost-tier-to-pct mapping) lives here, the shared core
handles the actual SmartRouter call.

Without this stage, the engine produces a list of high-risk
customers with retention_action="win_back_offer" but no
actual discount code exists in Shopify -- the merchant has
to mint one manually before the recommendation can ship.

Filters (returns None to skip):
  * ``risk_level`` not in {"critical", "high"} -- medium /
    low risk doesn't warrant the retention spend yet
  * ``retention_action`` != "win_back_offer" --
    personal_outreach / exclusive_access / loyalty_reward
    aren't mintable as one-shot codes (need operator action)
  * Router unavailable / capability missing / adapter
    rejection -- record_writeback captures the failure
    state for the learning loop

Discount value derives from ``estimated_cost_tier``:
  low    -> 10%
  medium -> 15%
  high   -> 20%

These mirror the loyalty / cart_recovery defaults; conservative
on purpose since retention offers can stack with other
discounts and unbounded percentages would compound.

Records via Pattern Z so every mint attempt feeds Phase 8's
learning loop -- the system can later correlate retention codes
with re-engagement (orders within 30 days of mint).
"""
from __future__ import annotations

from typing import Any

from engines._agi_context import (
    capture_decision_context,
    explain_guardrail_block,
    guardrail_enabled,
    should_block_unambiguous_negative,
)
from engines._recovery_codes import mint_recovery_code as _mint
from engines._writeback_recorder import record_writeback


# Code-name prefix. Distinguishes retention codes from other
# discount classes in the operator's Shopify admin view.
_CODE_PREFIX = "RETAIN"

# Default code TTL when the store payload doesn't specify one.
# Retention offers run longer than cart recovery (7d) because
# the customer hasn't abandoned a specific cart -- give them a
# 14-day window to re-engage at a convenient moment.
_DEFAULT_TTL_DAYS = 14

# Risk levels worth spending a retention code on. Medium and
# low risk customers are better targeted by cheaper engagement
# touches (email, loyalty program signal).
_RETENTION_RISK_LEVELS = {"critical", "high"}

# Retention actions that map to a discount code. Other actions
# (personal_outreach, exclusive_access, loyalty_reward) need
# human or non-discount intervention.
_MINTABLE_ACTIONS = {"win_back_offer"}

# Cost-tier -> percentage off mapping. Conservative on purpose;
# operators tune via the engine's config if a niche needs
# different defaults.
_COST_TIER_PCT: dict[str, float] = {
    "low": 10.0,
    "medium": 15.0,
    "high": 20.0,
}
_DEFAULT_PCT = 10.0


def mint_retention_code(
    prediction: dict[str, Any],
    customer: dict[str, Any],
    store: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Mint a one-shot Shopify discount code for a high-risk
    customer's win-back retention offer.

    Args:
        prediction: One prediction dict from
            ``ChurnPredictionEngine.run()``'s
            ``data.predictions[i]``. Must carry
            ``risk_level``, ``retention_action``, and the
            nested ``estimated_cost_tier`` (typically via the
            full retention dict, but the simplified shape
            with the cost tier as a top-level field is also
            tolerated).
        customer: Customer dict -- used for the code-name
            suffix so each retention code is unique.
        store: Optional store config -- looks for
            ``retention_code_ttl_days`` to override the
            14-day default.

    Returns:
        ``{"code", "discount_id", "ends_at", "applies_once",
        "customer_id"}`` on success, or ``None`` when filtered
        out (wrong risk level, non-mintable action,
        router unavailable, mint failed, or guardrail blocked).
    """
    risk_level = str(prediction.get("risk_level", "")).lower()
    if risk_level not in _RETENTION_RISK_LEVELS:
        return None

    retention_action = str(
        prediction.get("retention_action", ""),
    ).lower()
    if retention_action not in _MINTABLE_ACTIONS:
        return None

    cost_tier = str(
        prediction.get("estimated_cost_tier", "")
    ).lower()
    discount_pct = _COST_TIER_PCT.get(cost_tier, _DEFAULT_PCT)

    customer_id = (
        customer.get("id")
        or customer.get("customer_id")
        or prediction.get("customer_id")
        or "anon"
    )
    token = f"CUSTOMER{str(customer_id).upper()[:32]}"

    ttl_days = _DEFAULT_TTL_DAYS
    if isinstance(store, dict):
        try:
            override = int(
                store.get("retention_code_ttl_days") or 0,
            )
            if 1 <= override <= 90:
                ttl_days = override
        except (TypeError, ValueError):
            pass

    title = (
        f"Retention offer: {discount_pct:g}% off "
        f"(risk={risk_level})"
    )

    mint_params = {
        "token": token,
        "value": discount_pct,
        "value_kind": "percentage",
        "ttl_days": ttl_days,
        "customer_id": str(customer_id),
        "risk_level": risk_level,
    }

    # AGI Phase 2: capture decision context. Signal flows into
    # record_writeback regardless of v2 guardrail outcome.
    agi_context = capture_decision_context(
        engine="churn_prediction",
        action_type="mint_retention_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
    )
    agi_metrics = agi_context.get("metrics") or {}

    # AGI Phase 2 v2: guardrail. Opt-in via
    # ``SHOPAI_CHURN_PREDICTION_AGI_GUARDRAIL=1``. When the
    # captured signal is unambiguously negative, refuse to mint.
    if guardrail_enabled("churn_prediction") and \
            should_block_unambiguous_negative(agi_metrics):
        record_writeback(
            engine="churn_prediction",
            action_type="mint_retention_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params=mint_params,
            success=False,
            error=explain_guardrail_block(agi_metrics),
            metrics=agi_metrics,
        )
        return None

    minted = _mint(
        token=token,
        code_prefix=_CODE_PREFIX,
        value=discount_pct,
        value_kind="percentage",
        ttl_days=ttl_days,
        title=title,
    )

    # Phase 8: feed the autonomous learning loop. Metrics
    # passthrough preempts the auto-capture so the data
    # architecture sees the same signal the engine had at
    # decision time.
    record_writeback(
        engine="churn_prediction",
        action_type="mint_retention_code",
        capability="SHOPIFY_CREATE_DISCOUNT",
        params=mint_params,
        success=minted is not None,
        error=None if minted is not None else "mint_returned_none",
        metrics=agi_metrics or None,
    )

    if minted is None:
        return None

    return {
        **minted,
        "customer_id": str(customer_id),
    }
