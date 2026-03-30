"""CustomerLogic — deep business logic for customer-related engines.

Uses RecommendationIntelligence for product recommendations.
"""
from __future__ import annotations
import math
from typing import Any

from core.intelligence.recommendation_intelligence import RecommendationIntelligence

_ri = RecommendationIntelligence()


class CustomerLogic:
    """Real customer analytics computations."""

    CUSTOMER_ENGINES = {
        "customer_segmentation", "churn_prediction", "retention", "loyalty",
        "personalization", "recommendation", "customer_support", "sentiment_analysis",
        "review_management", "customer_journey", "ltv_prediction", "cohort_analysis",
        "customer_analytics", "customer_scoring", "nps_tracking", "customer_health",
    }

    def applies_to(self, engine_name: str) -> bool:
        return engine_name in self.CUSTOMER_ENGINES

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        customers = self._get_customers(data)

        if customers:
            result["customer_analysis"] = self._analyze_customers(customers)
            result["rfm_segments"] = self._rfm_segment(customers)
            result["churn_risks"] = self._detect_churn_risks(customers)
            result["high_value"] = self._identify_high_value(customers)
            result["score"] = self._customer_health_score(result)
            result["decision"] = "approve" if result["score"] >= 5 else "reject"
            result["reason"] = self._customer_reason(result)
        return result

    def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        result = {}
        customers = self._get_customers(data)

        if customers:
            result["segments"] = self._create_segments(customers)
            result["retention_plan"] = self._retention_plan(data)
            result["personalization_rules"] = self._personalization_rules(customers)

            # Product recommendations via RecommendationIntelligence
            purchase_history = data.get("purchase_history", data.get("orders", []))
            if isinstance(purchase_history, list) and purchase_history:
                target = customers[0].get("id", customers[0].get("name", ""))
                if target:
                    result["product_recommendations"] = _ri.collaborative_filter(purchase_history, str(target))

            # Cart cross-sell if cart data available
            cart = data.get("cart_items", data.get("cart_data", []))
            catalog = data.get("product_catalog", data.get("products", []))
            if isinstance(cart, list) and cart and isinstance(catalog, list) and catalog:
                result["cross_sell"] = _ri.cart_cross_sell(cart, catalog)

            result["generated"] = True
        return result

    def _analyze_customers(self, customers: list[dict]) -> dict:
        total = len(customers)
        order_counts = [int(c.get("orders", c.get("order_count", 0))) for c in customers]
        ltv_values = [float(c.get("ltv", c.get("lifetime_value", c.get("total_spent", 0)))) for c in customers]
        active = sum(1 for c in customers if c.get("status") != "churned" and c.get("active", True))

        return {
            "total": total,
            "active": active,
            "churned": total - active,
            "churn_rate": round((total - active) / total * 100, 1) if total else 0,
            "avg_orders": round(sum(order_counts) / total, 1) if total else 0,
            "avg_ltv": round(sum(ltv_values) / total, 2) if total else 0,
            "total_revenue": round(sum(ltv_values), 2),
            "repeat_rate": round(sum(1 for o in order_counts if o > 1) / total * 100, 1) if total else 0,
        }

    def _rfm_segment(self, customers: list[dict]) -> dict:
        segments = {"champions": [], "loyal": [], "potential": [], "at_risk": [], "lost": []}
        for c in customers:
            name = c.get("name", c.get("email", c.get("id", "unknown")))
            recency = int(c.get("days_since_last_order", c.get("recency", 999)))
            frequency = int(c.get("orders", c.get("order_count", 0)))
            monetary = float(c.get("ltv", c.get("total_spent", 0)))

            r = 5 if recency < 30 else 4 if recency < 60 else 3 if recency < 90 else 2 if recency < 180 else 1
            f = min(5, max(1, frequency))
            m = 5 if monetary > 500 else 4 if monetary > 200 else 3 if monetary > 100 else 2 if monetary > 50 else 1
            total = r + f + m

            if total >= 12: segments["champions"].append(name)
            elif total >= 9: segments["loyal"].append(name)
            elif total >= 6: segments["potential"].append(name)
            elif total >= 4: segments["at_risk"].append(name)
            else: segments["lost"].append(name)

        return {k: {"count": len(v), "customers": v[:10]} for k, v in segments.items()}

    def _detect_churn_risks(self, customers: list[dict]) -> list[dict]:
        risks = []
        for c in customers:
            recency = int(c.get("days_since_last_order", c.get("recency", 0)))
            frequency = int(c.get("orders", c.get("order_count", 0)))
            ltv = float(c.get("ltv", c.get("total_spent", 0)))

            risk_score = 0
            if recency > 90: risk_score += 3
            elif recency > 60: risk_score += 2
            elif recency > 30: risk_score += 1
            if frequency <= 1: risk_score += 2
            if ltv < 50: risk_score += 1

            if risk_score >= 4:
                risks.append({
                    "customer": c.get("name", c.get("email", "unknown")),
                    "risk_score": risk_score,
                    "risk_level": "high" if risk_score >= 6 else "medium",
                    "days_inactive": recency,
                    "ltv": ltv,
                    "action": "win_back_campaign" if recency > 90 else "retention_offer",
                })
        return sorted(risks, key=lambda x: x["risk_score"], reverse=True)[:20]

    def _identify_high_value(self, customers: list[dict]) -> list[dict]:
        valued = []
        for c in customers:
            ltv = float(c.get("ltv", c.get("total_spent", 0)))
            orders = int(c.get("orders", c.get("order_count", 0)))
            if ltv > 200 or orders > 5:
                valued.append({
                    "customer": c.get("name", c.get("email", "unknown")),
                    "ltv": ltv,
                    "orders": orders,
                    "tier": "vip" if ltv > 1000 else "gold" if ltv > 500 else "silver",
                })
        return sorted(valued, key=lambda x: x["ltv"], reverse=True)[:20]

    def _create_segments(self, customers: list[dict]) -> list[dict]:
        return [
            {"name": "new_customers", "criteria": "first purchase < 30 days", "count": sum(1 for c in customers if int(c.get("orders", 0)) <= 1 and int(c.get("recency", c.get("days_since_last_order", 0))) < 30)},
            {"name": "repeat_buyers", "criteria": "2+ orders", "count": sum(1 for c in customers if int(c.get("orders", c.get("order_count", 0))) >= 2)},
            {"name": "high_spenders", "criteria": "LTV > $200", "count": sum(1 for c in customers if float(c.get("ltv", c.get("total_spent", 0))) > 200)},
            {"name": "at_risk", "criteria": "inactive 60+ days", "count": sum(1 for c in customers if int(c.get("days_since_last_order", c.get("recency", 0))) > 60)},
            {"name": "dormant", "criteria": "inactive 180+ days", "count": sum(1 for c in customers if int(c.get("days_since_last_order", c.get("recency", 0))) > 180)},
        ]

    def _retention_plan(self, data: dict) -> dict:
        return {
            "strategies": [
                {"target": "at_risk", "action": "personalized_discount", "channel": "email", "timing": "immediate"},
                {"target": "new_customers", "action": "welcome_series", "channel": "email", "timing": "day_1_3_7"},
                {"target": "repeat_buyers", "action": "loyalty_program", "channel": "email+sms", "timing": "after_purchase"},
                {"target": "dormant", "action": "win_back_campaign", "channel": "email", "timing": "weekly"},
            ],
        }

    def _personalization_rules(self, customers: list[dict]) -> list[dict]:
        return [
            {"rule": "first_visit", "action": "show_bestsellers", "priority": 1},
            {"rule": "returning_no_purchase", "action": "show_recently_viewed", "priority": 2},
            {"rule": "cart_abandoner", "action": "show_cart_items_with_discount", "priority": 3},
            {"rule": "repeat_buyer", "action": "show_new_arrivals_in_category", "priority": 4},
            {"rule": "high_spender", "action": "show_premium_products", "priority": 5},
        ]

    def _customer_health_score(self, analysis: dict) -> float:
        score = 7.0
        ca = analysis.get("customer_analysis", {})
        if ca.get("churn_rate", 0) > 20: score -= 2
        if ca.get("repeat_rate", 0) < 20: score -= 1
        if ca.get("repeat_rate", 0) > 40: score += 1
        risks = analysis.get("churn_risks", [])
        high_risks = sum(1 for r in risks if r.get("risk_level") == "high")
        if high_risks > 5: score -= 1
        return max(min(round(score, 1), 10), 0)

    def _customer_reason(self, analysis: dict) -> str:
        ca = analysis.get("customer_analysis", {})
        return f"{ca.get('total', 0)} customers, {ca.get('churn_rate', 0):.1f}% churn, {ca.get('repeat_rate', 0):.1f}% repeat"

    @staticmethod
    def _get_customers(data: dict) -> list[dict]:
        for key in ("customer_data", "customers", "customer_list", "audience_data"):
            val = data.get(key, [])
            if isinstance(val, list) and val: return val
            if isinstance(val, dict): return [val]
        return []
