"""Affiliate Engine — commission calculator.

Calculates commissions due to each partner based on sales data
and commission tier structure.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_commissions(
    sales_data: list[dict[str, Any]],
    partners: list[dict[str, Any]],
    commission_rules: list[dict[str, Any]],
    program: dict[str, Any],
) -> dict[str, Any]:
    """Calculate commissions due per partner.

    Args:
        sales_data: List of SaleRecord dicts.
        partners: List of AffiliatePartner dicts.
        commission_rules: List of CommissionRule dicts.
        program: ProgramDesign dict from program_designer.

    Returns:
        Structured dict with commissions due.
    """
    try:
        sales = copy.deepcopy(sales_data)
        partners = copy.deepcopy(partners)
        tiers = program.get("commission_tiers", [])

        # Sort tiers by min_sales descending for matching
        tiers_sorted = sorted(
            tiers, key=lambda t: float(t.get("min_sales", 0)), reverse=True,
        )

        # Partner lookup
        partner_map = {str(p.get("id", "")): p for p in partners}

        # Aggregate sales per partner
        partner_revenue: dict[str, float] = {}
        for sale in sales:
            pid = str(sale.get("partner_id", ""))
            amount = float(sale.get("amount", 0.0))
            partner_revenue[pid] = partner_revenue.get(pid, 0.0) + amount

        commissions_due: list[dict[str, Any]] = []

        for pid, revenue in partner_revenue.items():
            partner = partner_map.get(pid, {})
            name = str(partner.get("name", pid))
            total_sales = float(partner.get("total_sales", 0.0)) + revenue

            # Find matching tier
            matched_tier = tiers_sorted[-1] if tiers_sorted else {
                "tier_name": "default",
                "commission_pct": 10.0,
                "bonus": 0.0,
            }
            for tier in tiers_sorted:
                if total_sales >= float(tier.get("min_sales", 0)):
                    matched_tier = tier
                    break

            commission_rate = float(matched_tier.get("commission_pct", 10.0))
            bonus = float(matched_tier.get("bonus", 0.0))
            commission_amount = round(revenue * (commission_rate / 100.0) + bonus, 2)

            commissions_due.append({
                "partner_id": pid,
                "name": name,
                "period_sales": round(revenue, 2),
                "commission_rate": commission_rate,
                "commission_amount": commission_amount,
                "tier": str(matched_tier.get("tier_name", "default")),
            })

        # Sort by commission amount descending
        commissions_due.sort(
            key=lambda x: x["commission_amount"], reverse=True,
        )

        return {
            "status": "success",
            "commissions_due": commissions_due,
        }
    except Exception as exc:
        return {
            "status": "error",
            "commissions_due": [],
            "error": f"Commission calculation failed: {exc}",
        }
