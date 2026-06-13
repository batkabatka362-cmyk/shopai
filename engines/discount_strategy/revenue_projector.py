"""Discount Strategy Engine — revenue projector.

Projects revenue impact: volume lift vs margin loss, break-even volume
calculation, and net profit impact.

Core math:
  base_profit_per_unit  = price * current_margin
  disc_profit_per_unit  = price * (1 - depth) * margin_at_depth
  margin_loss_per_unit  = base_profit_per_unit - disc_profit_per_unit
  discounted_margin     = margin_at_depth (from depth_calculator)

  break_even_volume = (margin_loss_per_unit * base_volume) / disc_profit_per_unit
    i.e., how many extra units needed so that total discounted profit >= total base profit

  net_profit_impact = projected_profit - base_profit
"""
from __future__ import annotations

from typing import Any


def project_revenue(
    margin_analyses: list[dict[str, Any]],
    sweet_spot_pct: float,
    volume_lift: float,
    margin_at_sweet_spot: float,
    duration_hours: int,
    target_reach_pct: float,
    response_rate: float,
    cannibalization_impact_pct: float,
) -> dict[str, Any]:
    """Project the revenue impact of the proposed discount.

    Args:
        margin_analyses: Per-product margin analysis list.
        sweet_spot_pct: Discount depth.
        volume_lift: Expected volume lift multiplier (e.g. 1.5 = 50% more).
        margin_at_sweet_spot: Margin after discount (0-1).
        duration_hours: How long the discount runs.
        target_reach_pct: Fraction of customer base reached (0-1).
        response_rate: Expected response/conversion rate (0-1).
        cannibalization_impact_pct: Fraction of regular sales cannibalized (0-1).

    Returns:
        Structured dict with RevenueProjection data.
    """
    try:
        if not margin_analyses:
            # W963-172: completing W963-161 -- the second
            # cold-start guard at line ~81 caught the
            # 'no-priced-products' path but this earlier
            # 'no-input-at-all' path still returned status=error.
            # Now both emit the same success-skip envelope with
            # the canonical success-path key schema so consumers
            # never KeyError on cold-start input.
            return {
                "status": "success",
                "projection": {
                    "base_revenue_daily": 0.0,
                    "projected_revenue_daily": 0.0,
                    "revenue_change_pct": 0.0,
                    "margin_loss_per_unit": 0.0,
                    "volume_lift_multiplier": 1.0,
                    "break_even_volume": 0.0,
                    "break_even_achievable": False,
                    "net_profit_impact": 0.0,
                    "projection_confidence": 0.1,
                },
                "error": "",
            }

        # --- Aggregate base metrics ---
        total_daily_revenue = 0.0
        total_daily_profit = 0.0
        total_daily_units = 0.0
        avg_price = 0.0
        avg_cogs = 0.0
        avg_margin = 0.0
        count = 0

        for a in margin_analyses:
            price = float(a.get("price", 0.0))
            cogs = float(a.get("cogs", 0.0))
            margin = float(a.get("current_margin", 0.0))
            daily_sales = float(a.get("daily_sales", 1.0))  # default 1 unit/day

            if price <= 0:
                continue

            total_daily_revenue += price * daily_sales
            total_daily_profit += (price - cogs) * daily_sales
            total_daily_units += daily_sales
            avg_price += price
            avg_cogs += cogs
            avg_margin += margin
            count += 1

        if count == 0 or total_daily_units <= 0:
            # W963-161 + W963-172: cold-start fallback. Must
            # mirror the SUCCESS-PATH key schema below (line ~188)
            # so downstream consumers reading
            # projection['base_revenue_daily'] / projection_
            # confidence / etc. don't KeyError on cold-start.
            # Pre-W963-172 the fallback used keys like
            # baseline_daily_revenue + confidence which no
            # success-path consumer expected -- silent crash on
            # the consumer side.
            return {
                "status": "success",
                "projection": {
                    "base_revenue_daily": 0.0,
                    "projected_revenue_daily": 0.0,
                    "revenue_change_pct": 0.0,
                    "margin_loss_per_unit": 0.0,
                    "volume_lift_multiplier": 1.0,
                    "break_even_volume": 0.0,
                    "break_even_achievable": False,
                    "net_profit_impact": 0.0,
                    "projection_confidence": 0.1,
                },
                "error": "",
            }

        avg_price /= count
        avg_cogs /= count
        avg_margin /= count

        # --- Compute per-unit economics ---
        base_profit_per_unit = avg_price * avg_margin
        discounted_price = avg_price * (1.0 - sweet_spot_pct)

        if discounted_price <= 0:
            return {
                "status": "error",
                "projection": {},
                "error": "Discounted price is zero or negative",
            }

        disc_profit_per_unit = discounted_price - avg_cogs
        margin_loss_per_unit = base_profit_per_unit - max(disc_profit_per_unit, 0.0)

        # --- Volume projection ---
        # Effective volume lift considers reach and response
        # volume_lift is the max theoretical lift; actual is scaled by targeting
        effective_lift = 1.0 + (volume_lift - 1.0) * target_reach_pct
        projected_daily_units = total_daily_units * effective_lift

        # --- Cannibalization adjustment ---
        # Some of the projected volume would have happened at full price
        cannibalized_units = total_daily_units * cannibalization_impact_pct
        # These units still sell, but at discounted margin instead of full margin
        # Net: we lose margin on cannibalized units
        incremental_units = projected_daily_units - total_daily_units

        # --- Revenue calculation ---
        base_revenue_daily = total_daily_revenue
        projected_revenue_daily = (
            # Non-cannibalized full-price sales
            (total_daily_units - cannibalized_units) * avg_price
            # Cannibalized sales at discounted price
            + cannibalized_units * discounted_price
            # Incremental sales at discounted price
            + incremental_units * discounted_price
        )

        revenue_change_pct = (
            (projected_revenue_daily - base_revenue_daily) / base_revenue_daily
            if base_revenue_daily > 0 else 0.0
        )

        # --- Profit calculation ---
        base_profit_daily = total_daily_profit
        projected_profit_daily = (
            # Non-cannibalized full-price profit
            (total_daily_units - cannibalized_units) * base_profit_per_unit
            # Cannibalized profit at discount
            + cannibalized_units * max(disc_profit_per_unit, 0.0)
            # Incremental profit
            + incremental_units * max(disc_profit_per_unit, 0.0)
        )
        net_profit_impact = projected_profit_daily - base_profit_daily

        # --- Break-even volume ---
        # How many total discounted units needed for discounted profit >= base profit
        # break_even_volume = base_profit_daily / disc_profit_per_unit
        if disc_profit_per_unit > 0:
            break_even_volume = base_profit_daily / disc_profit_per_unit
            break_even_achievable = projected_daily_units >= break_even_volume
        else:
            # Negative margin per unit — break-even impossible
            break_even_volume = float("inf")
            break_even_achievable = False

        # --- Confidence ---
        # Higher confidence when: volume lift is modest, cannibalization is low,
        # margins are healthy, and break-even is achievable
        confidence = _compute_confidence(
            volume_lift, cannibalization_impact_pct,
            margin_at_sweet_spot, break_even_achievable,
        )

        return {
            "status": "success",
            "projection": {
                "base_revenue_daily": round(base_revenue_daily, 2),
                "projected_revenue_daily": round(projected_revenue_daily, 2),
                "revenue_change_pct": round(revenue_change_pct, 4),
                "margin_loss_per_unit": round(margin_loss_per_unit, 4),
                "volume_lift_multiplier": round(effective_lift, 4),
                "break_even_volume": round(break_even_volume, 2) if break_even_volume != float("inf") else 999999.0,
                "break_even_achievable": break_even_achievable,
                "net_profit_impact": round(net_profit_impact, 2),
                "projection_confidence": round(confidence, 4),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "projection": {},
            "error": f"Revenue projection failed: {exc}",
        }


def _compute_confidence(
    volume_lift: float,
    cannibalization_pct: float,
    margin_at_depth: float,
    break_even_achievable: bool,
) -> float:
    """Compute projection confidence score (0-1).

    Confidence is higher when:
      - Volume lift assumption is modest (< 2x)
      - Cannibalization is low
      - Post-discount margin is healthy
      - Break-even is achievable
    """
    score = 0.70  # base confidence

    # Volume lift penalty: high lift assumptions are risky
    if volume_lift > 3.0:
        score -= 0.25
    elif volume_lift > 2.0:
        score -= 0.15
    elif volume_lift > 1.5:
        score -= 0.05

    # Cannibalization penalty
    score -= cannibalization_pct * 0.30

    # Margin health bonus
    if margin_at_depth >= 0.15:
        score += 0.10
    elif margin_at_depth >= 0.05:
        score += 0.05
    elif margin_at_depth < 0.0:
        score -= 0.20

    # Break-even bonus
    if break_even_achievable:
        score += 0.10
    else:
        score -= 0.15

    return max(0.05, min(0.95, score))
