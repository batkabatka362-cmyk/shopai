"""Main financial risk assessment engine.

Evaluates financial risks across six dimensions and calculates max loss
scenarios, capital recovery probability, and burn rate projections.
Returns the engine contract: {status, data, meta, error}.
"""

from __future__ import annotations

from typing import Any

from .data import (
    get_loss_probability,
    get_chargeback_rates,
    get_currency_volatility,
    get_margin_erosion,
    CASH_FLOW_BENCHMARKS,
)


def assess_financial_risk(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Assess financial risks for a product investment.

    Args:
        input_payload: dict with keys:
            - total_investment (float): total capital at risk in USD (required)
            - monthly_revenue_estimate (float): projected monthly revenue (required)
            - cogs_percent (float): COGS as % of revenue (default 0.35)
            - product_type (str): trending_fad|seasonal|evergreen|commodity|innovative|private_label
            - category (str): product category for chargeback data (default "general")
            - competition_level (str): high|moderate|low|differentiated|patented
            - currency_pair (str): e.g. "USD_CNY" (default "USD_CNY")
            - monthly_fixed_costs (float): rent, software, labor (default 500)
            - available_budget (float): total available capital (default = total_investment * 2)
            - target_margin (float): desired margin (default 0.30)
            - months_to_project (int): projection horizon (default 12)

    Returns:
        Engine contract dict {status, data, meta, error}.
    """
    try:
        total_investment = input_payload.get("total_investment")
        monthly_revenue = input_payload.get("monthly_revenue_estimate")

        if total_investment is None or monthly_revenue is None:
            return _error("total_investment and monthly_revenue_estimate are required")
        if total_investment <= 0:
            return _error("total_investment must be positive")
        if monthly_revenue < 0:
            return _error("monthly_revenue_estimate cannot be negative")

        cogs_pct = input_payload.get("cogs_percent", 0.35)
        product_type = input_payload.get("product_type", "evergreen")
        category = input_payload.get("category", "general")
        competition = input_payload.get("competition_level", "moderate_competition")
        currency_pair = input_payload.get("currency_pair", "USD_CNY")
        fixed_costs = input_payload.get("monthly_fixed_costs", 500.0)
        budget = input_payload.get("available_budget", total_investment * 2)
        target_margin = input_payload.get("target_margin", 0.30)
        months = input_payload.get("months_to_project", 12)

        # --- 1. Capital at risk (MOQ investment) ---
        budget_ratio = total_investment / budget if budget > 0 else 1.0
        capital_score = _score_capital_risk(total_investment, budget_ratio)

        # --- 2. Cash flow risk (time to positive) ---
        monthly_gross_profit = monthly_revenue * (1 - cogs_pct)
        monthly_net = monthly_gross_profit - fixed_costs
        months_to_recover = (
            round(total_investment / monthly_net, 1) if monthly_net > 0 else 99
        )
        cash_flow_score = _score_cash_flow(months_to_recover)

        # --- 3. Margin erosion risk ---
        erosion = get_margin_erosion(competition)
        margin_after_year = max(
            target_margin - erosion["annual_erosion"],
            erosion["stabilization_floor"],
        )
        margin_erosion_score = _score_margin_erosion(
            target_margin, margin_after_year, erosion["monthly_erosion"]
        )

        # --- 4. Currency risk ---
        volatility = get_currency_volatility(currency_pair)
        currency_impact = round(total_investment * cogs_pct * volatility, 2)
        currency_score = _score_currency_risk(volatility, currency_impact, total_investment)

        # --- 5. Refund/chargeback risk ---
        cb_rates = get_chargeback_rates(category)
        monthly_refund_cost = round(monthly_revenue * cb_rates["refund_rate"], 2)
        monthly_chargeback_cost = round(monthly_revenue * cb_rates["chargeback_rate"], 2)
        refund_score = _score_refund_risk(cb_rates)

        # --- 6. Scaling capital requirement ---
        scaling_capital = round(total_investment * 2.5, 2)  # Need ~2.5x to scale
        scaling_score = _score_scaling_risk(scaling_capital, budget)

        # --- Aggregate ---
        dimensions = {
            "capital_at_risk": capital_score,
            "cash_flow_risk": cash_flow_score,
            "margin_erosion": margin_erosion_score,
            "currency_risk": currency_score,
            "refund_chargeback": refund_score,
            "scaling_capital": scaling_score,
        }
        overall_score = round(sum(dimensions.values()) / len(dimensions), 1)
        risk_level = _classify_risk(overall_score)

        # --- Max loss scenario ---
        loss_probs = get_loss_probability(product_type)
        max_loss = round(total_investment + (fixed_costs * 3), 2)  # Investment + 3 months burn
        burn_rate = round(fixed_costs + (monthly_revenue * cogs_pct * 0.1), 2)

        # --- Capital recovery probability ---
        recovery_prob = round(
            loss_probs["break_even_prob"] + loss_probs["profit_prob"], 2
        )

        return {
            "status": "success",
            "data": {
                "overall_risk_score": overall_score,
                "risk_level": risk_level,
                "dimensions": dimensions,
                "max_loss_scenario": {
                    "total_max_loss": max_loss,
                    "investment_loss": total_investment,
                    "operating_burn": round(fixed_costs * 3, 2),
                    "probability_of_total_loss": loss_probs["total_loss_prob"],
                },
                "capital_recovery": {
                    "probability": recovery_prob,
                    "months_to_break_even": months_to_recover,
                    "monthly_net_cash_flow": round(monthly_net, 2),
                },
                "burn_rate_if_fails": {
                    "monthly_burn": burn_rate,
                    "months_until_depleted": round(budget / burn_rate, 1) if burn_rate > 0 else 99,
                },
                "margin_projection": {
                    "current_margin": target_margin,
                    "projected_margin_12m": round(margin_after_year, 4),
                    "erosion_rate_monthly": erosion["monthly_erosion"],
                },
                "refund_exposure": {
                    "monthly_refund_cost": monthly_refund_cost,
                    "monthly_chargeback_cost": monthly_chargeback_cost,
                    "annual_refund_exposure": round(monthly_refund_cost * 12, 2),
                },
                "currency_exposure": {
                    "currency_pair": currency_pair,
                    "annual_volatility": volatility,
                    "potential_impact_usd": currency_impact,
                },
                "scaling_requirements": {
                    "capital_needed_to_scale": scaling_capital,
                    "available_budget": budget,
                    "funding_gap": round(max(scaling_capital - budget, 0), 2),
                },
            },
            "meta": {
                "product_type": product_type,
                "category": category,
                "competition_level": competition,
                "months_projected": months,
            },
            "error": None,
        }

    except Exception as exc:
        return _error(f"Financial risk assessment failed: {exc}")


def _score_capital_risk(investment: float, budget_ratio: float) -> int:
    """Score capital at risk 0-100."""
    score = 10
    if investment > 50000:
        score += 30
    elif investment > 20000:
        score += 20
    elif investment > 5000:
        score += 10
    # Budget concentration penalty
    if budget_ratio > 0.60:
        score += 35
    elif budget_ratio > 0.40:
        score += 20
    elif budget_ratio > 0.25:
        score += 10
    return min(score, 100)


def _score_cash_flow(months_to_recover: float) -> int:
    """Score cash flow risk based on recovery time."""
    if months_to_recover >= 12:
        return 90
    if months_to_recover >= 8:
        return 70
    if months_to_recover >= 5:
        return 50
    if months_to_recover >= 3:
        return 30
    return 15


def _score_margin_erosion(current: float, projected: float, monthly_rate: float) -> int:
    """Score margin erosion risk."""
    erosion_pct = (current - projected) / current if current > 0 else 0
    if erosion_pct > 0.40:
        return 80
    if erosion_pct > 0.25:
        return 55
    if erosion_pct > 0.10:
        return 35
    return 15


def _score_currency_risk(volatility: float, impact: float, investment: float) -> int:
    """Score currency risk."""
    impact_ratio = impact / investment if investment > 0 else 0
    if volatility >= 0.09:
        return 60
    if volatility >= 0.07:
        return 45
    if volatility >= 0.04:
        return 25
    return 10


def _score_refund_risk(rates: dict[str, float]) -> int:
    """Score refund and chargeback risk."""
    combined = rates["refund_rate"] + rates["chargeback_rate"] + rates["fraud_rate"]
    if combined > 0.15:
        return 75
    if combined > 0.10:
        return 50
    if combined > 0.05:
        return 30
    return 15


def _score_scaling_risk(needed: float, available: float) -> int:
    """Score scaling capital requirement risk."""
    if available <= 0:
        return 90
    ratio = needed / available
    if ratio > 3.0:
        return 80
    if ratio > 2.0:
        return 55
    if ratio > 1.0:
        return 35
    return 15


def _classify_risk(score: float) -> str:
    """Classify overall risk level from score."""
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "moderate"
    return "low"


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
