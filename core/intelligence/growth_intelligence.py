"""GrowthIntelligence — channel maturity, micro-seasonality, opportunity cost.

TikTok 2022-д хямд байсан, 2024-д үнэтэй. ХЭЗЭЭ ямар channel-д орохыг мэдэх чухал.

Features:
  - Channel maturity scoring (entry/growth/mature/declining)
  - Micro-seasonality (time of day, day of week, payday, weather)
  - Opportunity cost reasoning (doing A means NOT doing B)
  - Channel-specific benchmarks and tactics
"""
from __future__ import annotations

import time
from typing import Any

from utils.logger import get_logger
from utils.helpers import safe_float

logger = get_logger("intelligence.growth")

# Channel maturity data (as of 2025-2026)
CHANNEL_MATURITY = {
    "facebook_ads": {
        "stage": "mature",
        "cpm_trend": "increasing",
        "avg_cpm": 12.0,
        "avg_cpc": 1.50,
        "avg_roas": 2.5,
        "competition": "high",
        "best_for": "Retargeting, lookalike audiences, broad reach",
        "declining_signal": "CPM rising 15-20% YoY, younger audiences leaving",
        "recommendation": "Focus on retargeting (high intent), reduce prospecting budget",
    },
    "instagram_ads": {
        "stage": "mature",
        "cpm_trend": "stable",
        "avg_cpm": 10.0,
        "avg_cpc": 1.20,
        "avg_roas": 2.8,
        "competition": "high",
        "best_for": "Visual products, lifestyle brands, UGC-heavy creative",
        "recommendation": "Reels-first creative strategy, influencer whitelisting",
    },
    "tiktok_ads": {
        "stage": "growth",
        "cpm_trend": "increasing",
        "avg_cpm": 6.0,
        "avg_cpc": 0.80,
        "avg_roas": 2.0,
        "competition": "medium",
        "best_for": "Gen Z/Millennial products, viral potential, trend-based",
        "opportunity": "Still cheaper than FB/IG, creator-style ads perform 3x better",
        "recommendation": "Enter now before costs rise. Use creator content, not polished ads.",
    },
    "google_search": {
        "stage": "mature",
        "cpm_trend": "stable",
        "avg_cpc": 2.50,
        "avg_roas": 4.0,
        "competition": "high",
        "best_for": "High-intent buyers, branded search, product-specific queries",
        "recommendation": "Essential channel. Focus on long-tail keywords for better CPC.",
    },
    "google_shopping": {
        "stage": "mature",
        "cpm_trend": "stable",
        "avg_cpc": 1.00,
        "avg_roas": 5.0,
        "competition": "high",
        "best_for": "Product-led businesses, price-competitive items",
        "recommendation": "Optimize feed: titles, images, prices. Use Performance Max.",
    },
    "google_performance_max": {
        "stage": "growth",
        "cpm_trend": "stable",
        "avg_roas": 3.5,
        "competition": "medium",
        "best_for": "Automated cross-channel Google advertising",
        "recommendation": "Feed it good creative and conversion data. Needs 30+ conversions/month.",
    },
    "email_marketing": {
        "stage": "mature",
        "cost": "low",
        "avg_roas": 42.0,
        "competition": "inbox_crowded",
        "best_for": "Retention, cart recovery, lifecycle marketing",
        "recommendation": "Highest ROI channel. Segment heavily, automate flows.",
    },
    "sms_marketing": {
        "stage": "growth",
        "cost": "medium",
        "avg_roas": 25.0,
        "competition": "low",
        "best_for": "Flash sales, back-in-stock alerts, delivery updates",
        "recommendation": "98% open rate. Use sparingly (2-4x/month) for highest value messages.",
    },
    "seo_organic": {
        "stage": "mature",
        "cost": "time_investment",
        "avg_roas": "long_term_high",
        "competition": "very_high",
        "best_for": "Long-term traffic, brand authority, content marketing",
        "recommendation": "6-12 month payoff. Start with blog + product page optimization.",
    },
    "influencer_marketing": {
        "stage": "growth",
        "cost": "variable",
        "avg_roas": 5.0,
        "competition": "medium",
        "best_for": "Brand awareness, trust building, user-generated content",
        "recommendation": "Micro-influencers (10K-50K) deliver 5x better ROI than mega.",
    },
    "pinterest_ads": {
        "stage": "growth",
        "cpm_trend": "stable",
        "avg_cpm": 5.0,
        "avg_roas": 2.5,
        "competition": "low",
        "best_for": "Home decor, fashion, food, DIY products",
        "recommendation": "Underpriced for visual products. High purchase intent audience.",
    },
    "youtube_ads": {
        "stage": "mature",
        "cpm_trend": "stable",
        "avg_cpm": 8.0,
        "avg_roas": 2.0,
        "competition": "medium",
        "best_for": "Brand building, product demos, educational content",
        "recommendation": "Best for products that need explanation. Shorts format growing fast.",
    },
}

# Micro-seasonality patterns
MICRO_SEASONALITY = {
    "time_of_day": {
        "6-10": {"activity": "morning_browse", "best_for": "email_send, content_publish", "conversion": "low"},
        "10-14": {"activity": "lunch_browse", "best_for": "social_ads, email_open", "conversion": "medium"},
        "14-17": {"activity": "afternoon_work", "best_for": "b2b_outreach, content_marketing", "conversion": "low"},
        "17-21": {"activity": "evening_shop", "best_for": "ad_campaigns, flash_sales", "conversion": "highest"},
        "21-24": {"activity": "late_browse", "best_for": "retargeting, impulse_offers", "conversion": "high"},
    },
    "day_of_week": {
        "monday": {"shopping_intent": "low", "best_for": "plan_campaigns, content_creation"},
        "tuesday": {"shopping_intent": "medium", "best_for": "email_campaigns, new_product_launch"},
        "wednesday": {"shopping_intent": "medium", "best_for": "mid_week_promotion"},
        "thursday": {"shopping_intent": "medium_high", "best_for": "pre_weekend_deals"},
        "friday": {"shopping_intent": "high", "best_for": "flash_sales, weekend_preview", "payday_boost": True},
        "saturday": {"shopping_intent": "highest", "best_for": "main_promotions, social_media"},
        "sunday": {"shopping_intent": "high", "best_for": "retargeting, last_chance_deals"},
    },
    "monthly_patterns": {
        "1st_week": {"spending": "high", "reason": "Payday effect", "action": "launch_promotions"},
        "2nd_week": {"spending": "medium", "reason": "Normal spending", "action": "maintain_campaigns"},
        "3rd_week": {"spending": "low", "reason": "Pre-payday tightening", "action": "reduce_ad_spend"},
        "4th_week": {"spending": "medium_high", "reason": "Month-end payday", "action": "launch_deals"},
    },
}


class GrowthIntelligence:
    """Channel maturity analysis and growth opportunity detection.

    Usage:
        gi = GrowthIntelligence()
        channels = gi.analyze_channels(budget=5000)
        timing = gi.get_optimal_timing()
        opportunities = gi.find_growth_opportunities(current_channels=["facebook_ads"])
    """

    def analyze_channels(
        self,
        budget: float = 5000,
        current_channels: list[str] | None = None,
        product_type: str = "general",
    ) -> dict[str, Any]:
        """Analyze all channels and recommend allocation."""
        current = set(current_channels or [])
        channel_analysis = []

        for name, data in CHANNEL_MATURITY.items():
            in_use = name in current
            stage = data["stage"]
            roas = safe_float(data.get("avg_roas", 0))

            opportunity_score = self._score_channel(name, data, product_type, in_use)

            channel_analysis.append({
                "channel": name,
                "stage": stage,
                "in_use": in_use,
                "avg_roas": roas if isinstance(roas, (int, float)) else 0,
                "competition": data.get("competition", "unknown"),
                "opportunity_score": opportunity_score,
                "recommendation": data.get("recommendation", ""),
                "best_for": data.get("best_for", ""),
            })

        channel_analysis.sort(key=lambda c: c["opportunity_score"], reverse=True)

        # Budget allocation
        allocation = self._allocate_budget(channel_analysis, budget)

        # Find untapped channels
        untapped = [c for c in channel_analysis if not c["in_use"] and c["opportunity_score"] > 60]

        return {
            "channels": channel_analysis,
            "budget_allocation": allocation,
            "untapped_opportunities": untapped[:3],
            "recommendation": self._top_recommendation(channel_analysis, current),
        }

    def get_optimal_timing(self) -> dict[str, Any]:
        """Get optimal timing for various actions based on micro-seasonality."""
        now = time.localtime()
        hour = now.tm_hour
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][now.tm_wday]
        day_of_month = now.tm_mday

        # Current time slot
        time_slot = "6-10"
        for slot in MICRO_SEASONALITY["time_of_day"]:
            start, end = map(int, slot.split("-"))
            if start <= hour < end:
                time_slot = slot
                break

        current_time = MICRO_SEASONALITY["time_of_day"].get(time_slot, {})
        current_day = MICRO_SEASONALITY["day_of_week"].get(weekday, {})

        # Monthly pattern
        week = "1st_week" if day_of_month <= 7 else "2nd_week" if day_of_month <= 14 else "3rd_week" if day_of_month <= 21 else "4th_week"
        monthly = MICRO_SEASONALITY["monthly_patterns"].get(week, {})

        return {
            "current": {
                "time_slot": time_slot,
                "activity": current_time.get("activity", ""),
                "conversion_level": current_time.get("conversion", ""),
                "day": weekday,
                "shopping_intent": current_day.get("shopping_intent", ""),
                "monthly_spending": monthly.get("spending", ""),
            },
            "best_actions_now": current_time.get("best_for", "").split(", "),
            "day_recommendation": current_day.get("best_for", ""),
            "monthly_action": monthly.get("action", ""),
            "optimal_windows": {
                "ad_launch": "17:00-21:00 (evening peak), Friday-Sunday",
                "email_send": "10:00-14:00 (lunch browse), Tuesday-Thursday",
                "content_publish": "8:00-12:00 (morning consumption), Tuesday",
                "flash_sale": "Friday 17:00 (payday + evening + weekend)",
                "seo_update": "02:00-06:00 (low traffic for site changes)",
            },
        }

    def find_growth_opportunities(
        self,
        current_channels: list[str] | None = None,
        monthly_revenue: float = 0,
    ) -> list[dict[str, Any]]:
        """Find specific growth opportunities based on current state."""
        opportunities = []
        current = set(current_channels or [])

        # Channel-based opportunities
        if "tiktok_ads" not in current:
            opportunities.append({
                "type": "new_channel",
                "channel": "tiktok_ads",
                "potential_lift": "+15-30% traffic",
                "effort": "medium",
                "reason": "Still in growth phase, CPMs 50% cheaper than Facebook",
            })

        if "email_marketing" not in current:
            opportunities.append({
                "type": "new_channel",
                "channel": "email_marketing",
                "potential_lift": "+20-40% revenue",
                "effort": "medium",
                "reason": "42x ROI — highest of any channel. Start with 3 automation flows.",
            })

        if "sms_marketing" not in current:
            opportunities.append({
                "type": "new_channel",
                "channel": "sms_marketing",
                "potential_lift": "+5-15% revenue",
                "effort": "low",
                "reason": "98% open rate within 3 minutes. Perfect for flash sales.",
            })

        if "pinterest_ads" not in current:
            opportunities.append({
                "type": "new_channel",
                "channel": "pinterest_ads",
                "potential_lift": "+10-20% traffic",
                "effort": "low",
                "reason": "Underpriced, high purchase intent. Great for visual products.",
            })

        # Optimization opportunities
        if "facebook_ads" in current:
            opportunities.append({
                "type": "optimize_existing",
                "channel": "facebook_ads",
                "potential_lift": "+10-20% ROAS",
                "effort": "low",
                "reason": "Shift budget from prospecting to retargeting. Test Advantage+ campaigns.",
            })

        if monthly_revenue > 10000 and "influencer_marketing" not in current:
            opportunities.append({
                "type": "new_channel",
                "channel": "influencer_marketing",
                "potential_lift": "+15-25% brand awareness",
                "effort": "medium",
                "reason": "At your revenue level, micro-influencer partnerships are cost-effective.",
            })

        opportunities.sort(key=lambda o: {"low": 3, "medium": 2, "high": 1}.get(o["effort"], 2), reverse=True)
        return opportunities

    def opportunity_cost(self, option_a: dict[str, Any], option_b: dict[str, Any]) -> dict[str, Any]:
        """Calculate opportunity cost: doing A means NOT doing B."""
        a_value = safe_float(option_a.get("expected_value", 0))
        b_value = safe_float(option_b.get("expected_value", 0))

        if a_value >= b_value:
            chosen, forgone = option_a, option_b
            cost = b_value
        else:
            chosen, forgone = option_b, option_a
            cost = a_value

        return {
            "chosen": chosen.get("name", "Option A"),
            "forgone": forgone.get("name", "Option B"),
            "chosen_value": max(a_value, b_value),
            "opportunity_cost": cost,
            "net_gain": abs(a_value - b_value),
            "recommendation": f"Choose '{chosen.get('name', 'A')}' — opportunity cost of ${cost:,.0f} is worth the ${abs(a_value - b_value):,.0f} net gain",
        }

    def _score_channel(self, name, data, product_type, in_use):
        score = 50
        stage = data.get("stage", "mature")
        if stage == "growth":
            score += 20
        elif stage == "entry":
            score += 30
        elif stage == "declining":
            score -= 20

        roas = safe_float(data.get("avg_roas", 0))
        if roas > 5:
            score += 15
        elif roas > 3:
            score += 10

        comp = data.get("competition", "medium")
        if comp == "low":
            score += 15
        elif comp == "very_high":
            score -= 10

        if not in_use:
            score += 10  # Untapped bonus

        return min(100, max(0, score))

    def _allocate_budget(self, channels, budget):
        scored = [c for c in channels if c["in_use"] or c["opportunity_score"] > 70]
        if not scored:
            return {"note": "No channels to allocate to"}

        total_score = sum(c["opportunity_score"] for c in scored[:5])
        allocation = {}
        for c in scored[:5]:
            pct = c["opportunity_score"] / max(total_score, 1)
            allocation[c["channel"]] = {
                "amount": round(budget * pct, 2),
                "pct": round(pct * 100, 1),
            }
        return allocation

    def _top_recommendation(self, channels, current):
        untapped_growth = [c for c in channels if not c["in_use"] and c["stage"] == "growth"]
        if untapped_growth:
            best = untapped_growth[0]
            return f"Expand to {best['channel']} — growth stage, {best['competition']} competition"
        return "All growth channels covered. Focus on optimization."
