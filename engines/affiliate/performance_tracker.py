"""Affiliate Engine — performance tracker.

Tracks affiliate partner performance with rankings, revenue trends,
and conversion metrics.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def track_performance(
    partners: list[dict[str, Any]],
    sales_data: list[dict[str, Any]],
    partner_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track and rank affiliate partner performance.

    Args:
        partners: List of AffiliatePartner dicts.
        sales_data: List of SaleRecord dicts.
        partner_scores: List of PartnerScore dicts from partner_evaluator.

    Returns:
        Structured dict with top performers.
    """
    try:
        partners = copy.deepcopy(partners)
        sales = copy.deepcopy(sales_data)
        scores = copy.deepcopy(partner_scores)

        partner_map = {str(p.get("id", "")): p for p in partners}
        score_map = {str(s.get("partner_id", "")): s for s in scores}

        # Aggregate period sales per partner
        partner_period_sales: dict[str, float] = {}
        partner_period_count: dict[str, int] = {}
        for sale in sales:
            pid = str(sale.get("partner_id", ""))
            amount = float(sale.get("amount", 0.0))
            partner_period_sales[pid] = partner_period_sales.get(pid, 0.0) + amount
            partner_period_count[pid] = partner_period_count.get(pid, 0) + 1

        performers: list[dict[str, Any]] = []

        for partner in partners:
            pid = str(partner.get("id", "unknown"))
            name = str(partner.get("name", ""))
            total_sales = float(partner.get("total_sales", 0.0))
            total_referrals = int(partner.get("total_referrals", 0))

            period_sales = partner_period_sales.get(pid, 0.0)
            period_count = partner_period_count.get(pid, 0)

            # Conversion rate
            conversion_rate = (
                round(period_count / total_referrals, 4)
                if total_referrals > 0 else 0.0
            )

            # Revenue trend: compare period sales to historical average
            if total_sales > 0 and period_sales > 0:
                # Assume 30-day period
                historical_monthly = total_sales / 12.0  # rough monthly average
                if historical_monthly > 0:
                    trend_ratio = period_sales / historical_monthly
                    if trend_ratio > 1.15:
                        trend = "growing"
                    elif trend_ratio > 0.85:
                        trend = "stable"
                    else:
                        trend = "declining"
                else:
                    trend = "new"
            else:
                trend = "inactive"

            performers.append({
                "partner_id": pid,
                "name": name,
                "total_sales": round(total_sales + period_sales, 2),
                "total_referrals": total_referrals,
                "conversion_rate": conversion_rate,
                "revenue_trend": trend,
                "rank": 0,  # filled below
            })

        # Rank by total sales
        performers.sort(key=lambda x: x["total_sales"], reverse=True)
        for idx, perf in enumerate(performers):
            perf["rank"] = idx + 1

        # Return top performers (top 10)
        top_performers = performers[:10]

        return {
            "status": "success",
            "top_performers": top_performers,
        }
    except Exception as exc:
        return {
            "status": "error",
            "top_performers": [],
            "error": f"Performance tracking failed: {exc}",
        }
