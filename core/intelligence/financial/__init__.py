"""Financial Depth — orchestrates 7 specialized financial analyzers.

This is the FLOW file. It only calls other modules. No logic here.
"""
from __future__ import annotations

from typing import Any

from .tax_nexus import analyze_tax_nexus
from .bnpl_analyzer import analyze_bnpl
from .dimensional_shipping import analyze_dimensional_shipping
from .working_capital import analyze_working_capital
from .payment_optimizer import optimize_payment_processor
from .chargeback_risk import assess_chargeback_risk
from .contribution_margin import contribution_margin_by_sku


class FinancialDepth:
    """Expert-level financial intelligence — flow orchestrator."""

    def full_analysis(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        revenue_by_state: dict[str, float] | None = None,
        current_processor: str = "shopify_payments",
    ) -> dict[str, Any]:
        return {
            "tax_nexus": analyze_tax_nexus(revenue_by_state or {}),
            "bnpl_opportunity": analyze_bnpl(products, orders),
            "shipping_optimization": analyze_dimensional_shipping(products),
            "working_capital": analyze_working_capital(orders),
            "payment_optimization": optimize_payment_processor(orders, current_processor),
            "chargeback_risk": assess_chargeback_risk(orders),
            "contribution_margins": contribution_margin_by_sku(products, orders),
        }
