"""ProactivePreparation — acts BEFORE problems happen.

System зөвхөн ОДОО юу болж байна гэдгийг мэддэг.
ProactivePreparation "7 хоногийн дараа inventory дуусна, ОДОО арга хэмжээ авах хэрэгтэй" гэж бодно.

Features:
  - Depletion prediction: inventory runs out in X days → act NOW
  - Cash flow protection: cash runs out in Y days → reduce spending
  - Pre-event preparation: Black Friday 60 days away → start prep
  - Auto-intervention thresholds:
    <10 days → demand reduction (price up, ads down)
    <3 days → emergency mode (stop all non-essential spending)
"""
from __future__ import annotations

import time
import math
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.proactive")

# Seasonal events with prep timelines
SEASONAL_EVENTS = {
    "black_friday": {"month": 11, "day": 27, "prep_days": 60, "priority": "critical",
                     "actions": ["increase_inventory_30pct", "prepare_discount_strategy", "boost_ad_budget_2x", "test_site_load"]},
    "cyber_monday": {"month": 12, "day": 2, "prep_days": 30, "priority": "high",
                     "actions": ["prepare_flash_deals", "email_teaser_campaign", "ensure_payment_capacity"]},
    "christmas": {"month": 12, "day": 25, "prep_days": 45, "priority": "critical",
                  "actions": ["gift_guide_content", "shipping_cutoff_date", "gift_wrapping_option", "extended_returns"]},
    "valentines": {"month": 2, "day": 14, "prep_days": 30, "priority": "medium",
                   "actions": ["couples_bundles", "gift_collection", "expedited_shipping"]},
    "back_to_school": {"month": 8, "day": 20, "prep_days": 30, "priority": "medium",
                       "actions": ["student_discounts", "bulk_bundle_deals", "category_reorganize"]},
    "new_year": {"month": 1, "day": 1, "prep_days": 14, "priority": "medium",
                 "actions": ["clearance_sale", "new_year_campaign", "inventory_audit"]},
    "mothers_day": {"month": 5, "day": 11, "prep_days": 21, "priority": "medium",
                    "actions": ["gift_bundles", "personalization_options", "express_shipping"]},
}

# Intervention thresholds
DEPLETION_THRESHOLDS = [
    {"days": 3, "severity": "emergency", "actions": ["pause_all_ads", "raise_price_15pct", "emergency_reorder", "disable_low_margin_items"]},
    {"days": 7, "severity": "critical", "actions": ["reduce_ad_spend_50pct", "raise_price_10pct", "expedited_reorder"]},
    {"days": 14, "severity": "warning", "actions": ["reorder_now", "reduce_promotions", "prepare_substitute_products"]},
    {"days": 30, "severity": "monitor", "actions": ["schedule_reorder", "review_demand_forecast"]},
]


class ProactivePreparation:
    """Predicts future problems and prepares in advance.

    Usage:
        prep = ProactivePreparation()
        result = prep.full_scan(products, orders, financial_data)
    """

    def full_scan(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
        financial: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full proactive scan: inventory, cash, seasonal."""
        return {
            "inventory_alerts": self.predict_depletions(products, orders),
            "cash_flow_warnings": self.predict_cash_flow(orders, financial),
            "seasonal_prep": self.check_seasonal_events(),
            "auto_interventions": self.generate_interventions(products, orders, financial),
        }

    def predict_depletions(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Predict when each product will run out of stock."""
        if not products:
            return []

        # Calculate daily sales velocity per product
        velocity: dict[str, float] = {}
        if orders:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                for item in order.get("line_items", []):
                    if isinstance(item, dict):
                        pid = str(item.get("product_id", ""))
                        qty = safe_int(item.get("quantity", 1))
                        velocity[pid] = velocity.get(pid, 0) + qty
            for pid in velocity:
                velocity[pid] = velocity[pid] / 30  # Assume 30-day window

        alerts = []
        for product in products:
            if not isinstance(product, dict):
                continue

            pid = str(product.get("id", ""))
            name = product.get("title", product.get("name", f"Product {pid}"))
            stock = safe_int(product.get("inventory_quantity", 0))
            daily = velocity.get(pid, 0.5)  # Default 0.5/day

            if stock <= 0:
                alerts.append({
                    "product": name, "product_id": pid,
                    "severity": "emergency", "days_remaining": 0,
                    "message": "OUT OF STOCK — losing sales NOW",
                    "actions": DEPLETION_THRESHOLDS[0]["actions"],
                })
                continue

            days_remaining = round(stock / max(daily, 0.01))

            for threshold in DEPLETION_THRESHOLDS:
                if days_remaining <= threshold["days"]:
                    alerts.append({
                        "product": name, "product_id": pid,
                        "severity": threshold["severity"],
                        "days_remaining": days_remaining,
                        "current_stock": stock,
                        "daily_velocity": round(daily, 2),
                        "message": f"Stock runs out in {days_remaining} days at current rate",
                        "actions": threshold["actions"],
                    })
                    break

        alerts.sort(key=lambda a: a["days_remaining"])
        return alerts

    def predict_cash_flow(
        self,
        orders: list[dict[str, Any]] | None = None,
        financial: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Predict cash flow problems before they happen."""
        warnings = []

        if not orders and not financial:
            return warnings

        # Daily revenue estimate
        order_values = [safe_float(o.get("total", 0)) for o in (orders or []) if isinstance(o, dict)]
        daily_revenue = sum(order_values) / 30 if order_values else 0
        daily_costs = daily_revenue * 0.7  # Rough: 70% of revenue goes to costs

        # Check from financial data
        if financial:
            pnl = financial.get("pnl", {})
            net_profit = safe_float(pnl.get("net_profit", 0))
            margin = safe_float(pnl.get("net_margin_pct", 0))

            if net_profit < 0:
                warnings.append({
                    "severity": "critical",
                    "type": "negative_profit",
                    "message": f"Operating at a LOSS (${net_profit:,.2f}). Cash will deplete.",
                    "days_to_crisis": round(abs(daily_revenue * 30 / max(abs(net_profit), 1)) * 30),
                    "actions": ["reduce_ad_spend", "raise_prices_on_low_margin", "pause_non_essential_costs"],
                })
            elif margin < 10:
                warnings.append({
                    "severity": "warning",
                    "type": "thin_margin",
                    "message": f"Net margin at {margin:.1f}% — vulnerable to cost increases",
                    "actions": ["review_pricing", "negotiate_supplier_terms", "reduce_shipping_costs"],
                })

        # Upcoming payment obligations estimate
        if daily_revenue > 0:
            monthly_ad_spend = daily_revenue * 0.15  # Typical 15% of revenue
            monthly_inventory = daily_revenue * 0.4   # 40% COGS
            monthly_obligations = monthly_ad_spend + monthly_inventory

            cash_runway = daily_revenue * 30 / max(monthly_obligations, 1) * 30
            if cash_runway < 30:
                warnings.append({
                    "severity": "warning",
                    "type": "cash_runway",
                    "message": f"Cash runway approximately {cash_runway:.0f} days",
                    "actions": ["extend_supplier_payment_terms", "reduce_inventory_orders", "consider_financing"],
                })

        return warnings

    def check_seasonal_events(self) -> list[dict[str, Any]]:
        """Check for upcoming seasonal events that need preparation."""
        now = time.localtime()
        current_month = now.tm_mon
        current_day = now.tm_mday
        current_year = now.tm_year

        upcoming = []
        for event_name, config in SEASONAL_EVENTS.items():
            event_month = config["month"]
            event_day = config["day"]
            prep_days = config["prep_days"]

            # Calculate days until event
            try:
                import datetime
                event_date = datetime.date(current_year, event_month, event_day)
                today = datetime.date(current_year, current_month, current_day)
                if event_date < today:
                    event_date = datetime.date(current_year + 1, event_month, event_day)
                days_until = (event_date - today).days
            except Exception:
                continue

            if days_until <= prep_days:
                prep_urgency = "overdue" if days_until <= 0 else "urgent" if days_until < 7 else "active" if days_until < prep_days / 2 else "planning"
                upcoming.append({
                    "event": event_name,
                    "days_until": days_until,
                    "prep_days": prep_days,
                    "priority": config["priority"],
                    "prep_urgency": prep_urgency,
                    "actions": config["actions"],
                    "message": f"{event_name.replace('_', ' ').title()} in {days_until} days — {prep_urgency} prep phase",
                })

        upcoming.sort(key=lambda e: e["days_until"])
        return upcoming

    def generate_interventions(
        self,
        products: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
        financial: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate automatic interventions based on all predictions."""
        interventions = []

        # Inventory interventions
        depletions = self.predict_depletions(products, orders)
        for alert in depletions:
            if alert["severity"] in ("emergency", "critical"):
                interventions.append({
                    "trigger": f"inventory_depletion:{alert['product_id']}",
                    "severity": alert["severity"],
                    "actions": alert["actions"],
                    "reason": alert["message"],
                })

        # Cash flow interventions
        cash_warnings = self.predict_cash_flow(orders, financial)
        for warning in cash_warnings:
            if warning["severity"] == "critical":
                interventions.append({
                    "trigger": f"cash_flow:{warning['type']}",
                    "severity": "critical",
                    "actions": warning["actions"],
                    "reason": warning["message"],
                })

        return interventions
