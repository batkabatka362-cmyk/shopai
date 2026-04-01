"""Customer Journey — full lifecycle orchestration intelligence.

What veterans know:
  - 7+ stages: Awareness → Interest → Consideration → Purchase → Delivery → Use → Advocacy
  - Traffic-source specific landing pages increase conversion 20-30%
  - Post-purchase experience determines LTV more than acquisition
  - Surprise & delight automation increases retention 30%+
  - Winback sequences: soft (30d) → value (60d) → last chance (90d)
  - Purchase pattern recognition enables predictive marketing
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float, safe_int

logger = get_logger("intelligence.customer_journey")


# Customer lifecycle stages
LIFECYCLE_STAGES = {
    "prospect": {
        "description": "Visited but never purchased",
        "goal": "Convert to first purchase",
        "channels": ["retargeting_ads", "email_welcome_series", "social_proof"],
        "kpi": "conversion_rate",
    },
    "first_buyer": {
        "description": "Made 1 purchase",
        "goal": "Convert to repeat buyer",
        "channels": ["post_purchase_email", "product_recommendations", "review_request"],
        "kpi": "repeat_purchase_rate",
    },
    "repeat_buyer": {
        "description": "Made 2-4 purchases",
        "goal": "Build loyalty and increase frequency",
        "channels": ["loyalty_program", "exclusive_offers", "cross_sell"],
        "kpi": "purchase_frequency",
    },
    "loyal": {
        "description": "Made 5+ purchases",
        "goal": "Turn into advocate",
        "channels": ["vip_access", "referral_program", "ambassador_program"],
        "kpi": "referral_rate",
    },
    "at_risk": {
        "description": "No purchase in 60-90 days (was active)",
        "goal": "Re-engage before churn",
        "channels": ["winback_email", "personalized_offer", "feedback_request"],
        "kpi": "reactivation_rate",
    },
    "lapsed": {
        "description": "No purchase in 90+ days",
        "goal": "Last attempt to recover",
        "channels": ["final_offer_email", "survey", "unsubscribe_alternative"],
        "kpi": "recovery_rate",
    },
}

# Post-purchase experience timeline
POST_PURCHASE_SEQUENCE = [
    {"day": 0, "action": "order_confirmation", "channel": "email", "content": "Thank you + order details + expected delivery"},
    {"day": 1, "action": "shipping_notification", "channel": "email+sms", "content": "Your order is on its way + tracking"},
    {"day": 3, "action": "delivery_check", "channel": "email", "content": "Has your order arrived? Need help?"},
    {"day": 7, "action": "review_request", "channel": "email", "content": "How do you like it? Leave a review for 10% off next order"},
    {"day": 14, "action": "cross_sell", "channel": "email", "content": "Customers who bought X also loved Y"},
    {"day": 30, "action": "replenishment_reminder", "channel": "email", "content": "Time for a refill? (if consumable)"},
    {"day": 45, "action": "loyalty_invite", "channel": "email", "content": "Join our loyalty program for exclusive benefits"},
]

# Surprise & delight triggers
SURPRISE_DELIGHT_TRIGGERS = [
    {"trigger": "3rd_order", "action": "handwritten_note", "cost": 2.0, "retention_lift": 0.15},
    {"trigger": "birthday", "action": "birthday_discount_20pct", "cost": "discount", "retention_lift": 0.10},
    {"trigger": "1_year_anniversary", "action": "anniversary_gift", "cost": 5.0, "retention_lift": 0.20},
    {"trigger": "high_value_order", "action": "free_sample_insert", "cost": 3.0, "retention_lift": 0.12},
    {"trigger": "5th_order", "action": "vip_status_upgrade", "cost": 0, "retention_lift": 0.25},
]

# Winback sequence
WINBACK_SEQUENCE = [
    {"days_inactive": 30, "stage": "soft", "subject": "We miss you!", "offer": "none", "tone": "Friendly reminder"},
    {"days_inactive": 45, "stage": "value", "subject": "See what's new", "offer": "free_shipping", "tone": "Show new products + social proof"},
    {"days_inactive": 60, "stage": "incentive", "subject": "A gift for you", "offer": "15%_off", "tone": "Personalized discount"},
    {"days_inactive": 90, "stage": "last_chance", "subject": "Last chance: 25% off", "offer": "25%_off", "tone": "Urgency + biggest offer"},
    {"days_inactive": 120, "stage": "sunset", "subject": "Should we stop emailing?", "offer": "none", "tone": "Respect + final attempt"},
]

# Traffic source → optimal landing page type
TRAFFIC_SOURCE_PAGES = {
    "facebook_ad": {"page_type": "social_proof_heavy", "elements": ["ugc_photos", "review_carousel", "impulse_cta"], "lift": "20-30%"},
    "google_search": {"page_type": "intent_focused", "elements": ["product_specs", "comparison_table", "trust_badges"], "lift": "15-25%"},
    "google_shopping": {"page_type": "product_detail", "elements": ["large_images", "price_comparison", "fast_checkout"], "lift": "10-20%"},
    "instagram": {"page_type": "visual_lifestyle", "elements": ["lifestyle_photos", "influencer_content", "shoppable_gallery"], "lift": "25-35%"},
    "tiktok": {"page_type": "video_first", "elements": ["product_video", "creator_content", "trending_badge"], "lift": "20-30%"},
    "email": {"page_type": "personalized", "elements": ["name_greeting", "past_purchase_related", "exclusive_badge"], "lift": "15-20%"},
    "organic_search": {"page_type": "seo_optimized", "elements": ["comprehensive_content", "faq", "schema_markup"], "lift": "10-15%"},
    "direct": {"page_type": "standard", "elements": ["full_catalog", "bestsellers", "new_arrivals"], "lift": "baseline"},
    "referral": {"page_type": "trust_focused", "elements": ["referrer_mention", "welcome_discount", "social_proof"], "lift": "15-25%"},
}


class CustomerJourney:
    """Full customer lifecycle orchestration engine."""

    def full_analysis(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run full customer journey analysis."""
        return {
            "lifecycle_segments": self.segment_by_lifecycle(customers, orders),
            "journey_map": self.map_customer_journeys(customers, orders),
            "winback_candidates": self.identify_winback_candidates(customers, orders),
            "surprise_delight_plan": self.plan_surprise_delight(customers, orders),
            "landing_page_strategy": self.recommend_landing_pages(),
            "post_purchase_plan": self.get_post_purchase_plan(),
        }

    def segment_by_lifecycle(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Segment customers by lifecycle stage."""
        now = time.time()
        segments: dict[str, list[dict[str, Any]]] = {stage: [] for stage in LIFECYCLE_STAGES}

        for customer in customers:
            if not isinstance(customer, dict):
                continue

            order_count = safe_int(customer.get("orders_count", 0))
            last_order_days = safe_int(customer.get("days_since_last_order", 999))

            # Also check from orders list
            if orders and last_order_days == 999:
                cid = customer.get("id")
                customer_orders = [
                    o for o in orders
                    if isinstance(o, dict)
                    and (o.get("customer_id") == cid or o.get("customer", {}).get("id") == cid)
                ]
                if customer_orders:
                    order_count = max(order_count, len(customer_orders))

            name = customer.get("name", customer.get("email", f"Customer {customer.get('id', '?')}"))
            entry = {"name": name, "id": customer.get("id"), "orders": order_count, "days_inactive": last_order_days}

            if order_count == 0:
                segments["prospect"].append(entry)
            elif last_order_days > 90:
                segments["lapsed"].append(entry)
            elif last_order_days > 60:
                segments["at_risk"].append(entry)
            elif order_count >= 5:
                segments["loyal"].append(entry)
            elif order_count >= 2:
                segments["repeat_buyer"].append(entry)
            else:
                segments["first_buyer"].append(entry)

        total = len(customers)
        summary = {}
        for stage, members in segments.items():
            count = len(members)
            info = LIFECYCLE_STAGES[stage]
            summary[stage] = {
                "count": count,
                "pct": round(count / max(total, 1) * 100, 1),
                "goal": info["goal"],
                "recommended_channels": info["channels"],
                "kpi": info["kpi"],
            }

        return {
            "total_customers": total,
            "segments": summary,
            "top_action": self._top_lifecycle_action(summary),
        }

    def map_customer_journeys(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Map the typical customer journey and identify drop-off points."""
        total = len(customers)
        if not total:
            return {"status": "no_data"}

        order_counts = [safe_int(c.get("orders_count", 0)) for c in customers if isinstance(c, dict)]
        at_least_1 = sum(1 for oc in order_counts if oc >= 1)
        at_least_2 = sum(1 for oc in order_counts if oc >= 2)
        at_least_3 = sum(1 for oc in order_counts if oc >= 3)
        at_least_5 = sum(1 for oc in order_counts if oc >= 5)

        funnel = [
            {"stage": "Visitors → First Purchase", "rate": round(at_least_1 / max(total, 1) * 100, 1), "count": at_least_1},
            {"stage": "First → Second Purchase", "rate": round(at_least_2 / max(at_least_1, 1) * 100, 1), "count": at_least_2},
            {"stage": "Second → Third Purchase", "rate": round(at_least_3 / max(at_least_2, 1) * 100, 1), "count": at_least_3},
            {"stage": "Third → Loyal (5+)", "rate": round(at_least_5 / max(at_least_3, 1) * 100, 1), "count": at_least_5},
        ]

        # Find biggest drop-off
        biggest_drop = min(funnel, key=lambda f: f["rate"])

        return {
            "funnel": funnel,
            "biggest_dropoff": biggest_drop["stage"],
            "dropoff_rate": biggest_drop["rate"],
            "recommendation": f"Focus on improving '{biggest_drop['stage']}' — currently only {biggest_drop['rate']}% conversion",
        }

    def identify_winback_candidates(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Identify customers for winback campaigns by stage."""
        candidates: dict[str, list] = {s["stage"]: [] for s in WINBACK_SEQUENCE}

        for customer in customers:
            if not isinstance(customer, dict):
                continue

            days_inactive = safe_int(customer.get("days_since_last_order", 0))
            order_count = safe_int(customer.get("orders_count", 0))
            if order_count == 0 or days_inactive < 30:
                continue

            name = customer.get("name", customer.get("email", "?"))
            for stage in WINBACK_SEQUENCE:
                if days_inactive >= stage["days_inactive"]:
                    matching_stage = stage["stage"]

            for stage in WINBACK_SEQUENCE:
                if stage["days_inactive"] <= days_inactive < stage.get("_next", 999):
                    candidates[stage["stage"]].append({
                        "name": name,
                        "days_inactive": days_inactive,
                        "past_orders": order_count,
                    })
                    break

        # Fill in _next thresholds for matching
        total_candidates = sum(len(v) for v in candidates.values())

        return {
            "total_winback_candidates": total_candidates,
            "by_stage": {
                stage: {
                    "count": len(members),
                    "offer": next(s["offer"] for s in WINBACK_SEQUENCE if s["stage"] == stage),
                    "subject_line": next(s["subject"] for s in WINBACK_SEQUENCE if s["stage"] == stage),
                }
                for stage, members in candidates.items()
            },
            "sequence": WINBACK_SEQUENCE,
        }

    def plan_surprise_delight(
        self,
        customers: list[dict[str, Any]],
        orders: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Plan surprise & delight moments to increase retention 15-25%."""
        eligible: dict[str, int] = {}

        for customer in customers:
            if not isinstance(customer, dict):
                continue
            order_count = safe_int(customer.get("orders_count", 0))

            for trigger in SURPRISE_DELIGHT_TRIGGERS:
                t = trigger["trigger"]
                if t == "3rd_order" and order_count == 3:
                    eligible[t] = eligible.get(t, 0) + 1
                elif t == "5th_order" and order_count == 5:
                    eligible[t] = eligible.get(t, 0) + 1
                elif t == "high_value_order" and order_count >= 1:
                    eligible[t] = eligible.get(t, 0) + 1

        return {
            "triggers": SURPRISE_DELIGHT_TRIGGERS,
            "eligible_customers": eligible,
            "estimated_retention_lift": "15-25% for customers who receive surprise moments",
            "key_insight": "The cost of a $3 insert card is trivial compared to the $50+ CAC of acquiring a new customer",
        }

    def recommend_landing_pages(self) -> dict[str, Any]:
        """Recommend traffic-source specific landing pages."""
        return {
            "strategy": TRAFFIC_SOURCE_PAGES,
            "key_insight": "Traffic-source specific landing pages increase conversion 20-30%. "
                          "A Facebook ad visitor expects social proof and impulse-buy CTAs, while "
                          "a Google Search visitor expects specs and comparisons.",
            "priority": [
                "facebook_ad (highest volume typically)",
                "google_search (highest intent)",
                "email (highest conversion rate)",
            ],
        }

    def get_post_purchase_plan(self) -> dict[str, Any]:
        """Get the post-purchase experience sequence."""
        return {
            "sequence": POST_PURCHASE_SEQUENCE,
            "key_insight": "Post-purchase experience determines LTV more than acquisition. "
                          "A customer who gets a review request on day 7 is 3x more likely to leave one "
                          "than one who gets it on day 30.",
        }

    def _top_lifecycle_action(self, summary: dict[str, Any]) -> str:
        """Determine the single most impactful lifecycle action."""
        at_risk_pct = summary.get("at_risk", {}).get("pct", 0)
        first_buyer_pct = summary.get("first_buyer", {}).get("pct", 0)
        prospect_pct = summary.get("prospect", {}).get("pct", 0)

        if at_risk_pct > 20:
            return f"URGENT: {at_risk_pct}% customers at risk of churn — launch winback campaign immediately"
        if first_buyer_pct > 40:
            return f"{first_buyer_pct}% are one-time buyers — focus on converting to repeat with post-purchase sequence"
        if prospect_pct > 50:
            return f"{prospect_pct}% are prospects — improve first-purchase conversion with welcome series"
        return "Customer lifecycle is balanced — focus on loyalty program expansion"
