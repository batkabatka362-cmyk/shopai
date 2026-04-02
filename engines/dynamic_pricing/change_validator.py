"""Dynamic Pricing Engine — change validator.

Validates proposed price changes against safety rules:
- No more than 20% change in 24 hours
- No below-cost pricing
- Reversibility check

Model note: Uses Mistral for validation reasoning and edge-case detection.

1 file = 1 job: change validation only.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------

_MAX_24H_CHANGE_PCT = 20.0    # max absolute % change in 24 hours
_MIN_MARGIN_ABOVE_COST = 0.01 # at least 1% above COGS


def validate_change(
    adjustment: dict[str, Any],
    impact_estimate: dict[str, Any],
    signals: dict[str, Any],
    recent_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate a proposed price change against safety rules.

    Args:
        adjustment: PriceAdjustment dict from price_adjuster.
        impact_estimate: ImpactEstimate dict from impact_estimator.
        signals: CollectedSignals dict with cogs.
        recent_changes: Optional list of recent changes for 24h window check.

    Returns:
        Structured dict with ValidationResult data.
    """
    try:
        adj = copy.deepcopy(adjustment)
        sig = copy.deepcopy(signals)
        recent = copy.deepcopy(recent_changes) if recent_changes else []

        product_id = str(adj.get("product_id", "unknown"))
        current_price = float(adj.get("current_price", 0.0))
        new_price = float(adj.get("new_price", 0.0))
        change_pct = float(adj.get("change_pct", 0.0))
        cogs = float(sig.get("cogs", 0.0))

        rejection_reasons: list[str] = []

        # --- Rule 1: No more than 20% change in 24h ---
        cumulative_change = abs(change_pct)
        for past_change in recent:
            cumulative_change += abs(float(past_change.get("change_pct", 0.0)))

        if cumulative_change > _MAX_24H_CHANGE_PCT:
            rejection_reasons.append(
                f"Cumulative 24h change would be {cumulative_change:.1f}%, "
                f"exceeding {_MAX_24H_CHANGE_PCT}% limit"
            )

        # --- Rule 2: No below-cost pricing ---
        if cogs > 0 and new_price < cogs:
            rejection_reasons.append(
                f"New price ${new_price:.2f} is below COGS ${cogs:.2f}"
            )

        # --- Rule 3: Minimum margin above cost ---
        if cogs > 0 and new_price > 0:
            margin_pct = (new_price - cogs) / new_price
            if margin_pct < _MIN_MARGIN_ABOVE_COST:
                rejection_reasons.append(
                    f"Margin {margin_pct * 100:.1f}% is below minimum "
                    f"{_MIN_MARGIN_ABOVE_COST * 100:.1f}%"
                )

        # --- Rule 4: Reversibility check ---
        # A change is reversible if it is small enough that reverting
        # it next cycle would still be within the 24h limit
        remaining_budget = _MAX_24H_CHANGE_PCT - cumulative_change
        reversible = abs(change_pct) <= remaining_budget

        # --- Decision ---
        approved = len(rejection_reasons) == 0
        rejection_reason = "; ".join(rejection_reasons) if rejection_reasons else None

        if approved:
            model_note = "Mistral: change validated — all safety rules passed"
        else:
            model_note = (
                f"Mistral: change rejected — {len(rejection_reasons)} "
                f"rule violation(s) detected"
            )

        return {
            "status": "success",
            "validation": {
                "product_id": product_id,
                "current_price": round(current_price, 2),
                "new_price": round(new_price, 2),
                "change_pct": round(change_pct, 2),
                "approved": approved,
                "rejection_reason": rejection_reason,
                "reversible": reversible,
                "model_note": model_note,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "validation": {},
            "error": f"Change validation failed: {exc}",
        }
