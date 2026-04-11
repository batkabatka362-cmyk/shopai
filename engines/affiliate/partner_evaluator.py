"""Affiliate Engine — partner evaluator.

Scores affiliate partners based on sales performance, conversion rates,
and quality metrics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def evaluate_partners(
    partners: list[dict[str, Any]],
    sales_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate and score each affiliate partner.

    Args:
        partners: List of AffiliatePartner dicts.
        sales_data: List of SaleRecord dicts.

    Returns:
        Structured dict with partner scores.
    """
    try:
        partners = copy.deepcopy(partners)
        sales = copy.deepcopy(sales_data)

        # Build per-partner sales aggregates
        partner_sales: dict[str, list[dict[str, Any]]] = {}
        for sale in sales:
            pid = str(sale.get("partner_id", ""))
            if pid:
                partner_sales.setdefault(pid, []).append(sale)

        partner_scores: list[dict[str, Any]] = []

        for partner in partners:
            pid = str(partner.get("id", "unknown"))
            name = str(partner.get("name", ""))
            total_sales = float(partner.get("total_sales", 0.0))
            total_referrals = int(partner.get("total_referrals", 0))

            # Calculate from actual sales data
            p_sales = partner_sales.get(pid, [])
            period_revenue = sum(float(s.get("amount", 0.0)) for s in p_sales)
            period_count = len(p_sales)

            # Conversion rate: sales / referrals
            if total_referrals > 0:
                conversion_rate = round(period_count / total_referrals, 4)
            else:
                conversion_rate = 0.0

            # Average order value
            avg_order_value = (
                round(period_revenue / period_count, 2)
                if period_count > 0 else 0.0
            )

            # Composite score (0-100)
            # Revenue weight: 40%, Conversion: 30%, AOV: 30%
            revenue_score = min(period_revenue / 10000.0, 1.0) * 40.0
            conv_score = min(conversion_rate / 0.10, 1.0) * 30.0
            aov_score = min(avg_order_value / 100.0, 1.0) * 30.0
            score = round(revenue_score + conv_score + aov_score, 1)

            # Quality tier
            if score >= 75:
                tier = "platinum"
            elif score >= 50:
                tier = "gold"
            elif score >= 25:
                tier = "silver"
            elif score > 0:
                tier = "bronze"
            else:
                tier = "inactive"

            partner_scores.append({
                "partner_id": pid,
                "name": name,
                "score": score,
                "conversion_rate": conversion_rate,
                "avg_order_value": avg_order_value,
                "quality_tier": tier,
            })

        # Sort by score descending
        partner_scores.sort(key=lambda x: x["score"], reverse=True)

        return {
            "status": "success",
            "partner_scores": partner_scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "partner_scores": [],
            "error": f"Partner evaluation failed: {exc}",
        }
