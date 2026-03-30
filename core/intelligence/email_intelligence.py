"""EmailIntelligence — real email marketing optimization.

  - Subject line scoring (word power, length, emoji, urgency)
  - Send time optimization (per customer timezone + engagement history)
  - Automated flow builder (welcome → nurture → convert → retain)
  - Shopify-specific triggers (abandoned cart, post-purchase, win-back)
"""
from __future__ import annotations

import hashlib
import math
from typing import Any


# Power words that increase open rates
POWER_WORDS = {
    "urgency": ["last chance", "ending soon", "today only", "limited time", "hurry", "now", "final"],
    "curiosity": ["secret", "reveal", "discover", "surprising", "behind the scenes", "sneak peek"],
    "value": ["free", "save", "discount", "exclusive", "deal", "bonus", "gift"],
    "personal": ["you", "your", "personalized", "just for you", "handpicked"],
    "social": ["trending", "bestseller", "popular", "favorite", "loved by"],
}

# Optimal send times by day (hour in UTC)
OPTIMAL_SEND_HOURS = {
    0: 10, 1: 10, 2: 14, 3: 10, 4: 10, 5: 9, 6: 10,  # Mon-Sun
}


class EmailIntelligence:
    """Real email marketing intelligence for e-commerce."""

    def score_subject_line(self, subject: str) -> dict[str, Any]:
        """Score an email subject line (0-100) with specific improvement suggestions."""
        if not subject:
            return {"score": 0, "error": "empty subject"}

        score = 50  # Base
        factors = []

        # Length (optimal: 30-50 chars)
        length = len(subject)
        if 30 <= length <= 50:
            score += 10
            factors.append({"factor": "length", "impact": "+10", "detail": f"{length} chars — optimal range"})
        elif length < 20:
            score -= 10
            factors.append({"factor": "length", "impact": "-10", "detail": f"{length} chars — too short"})
        elif length > 60:
            score -= 15
            factors.append({"factor": "length", "impact": "-15", "detail": f"{length} chars — will be truncated on mobile"})
        else:
            factors.append({"factor": "length", "impact": "0", "detail": f"{length} chars — acceptable"})

        # Power words
        subject_lower = subject.lower()
        power_hits = {}
        for category, words in POWER_WORDS.items():
            for word in words:
                if word in subject_lower:
                    power_hits[category] = word
                    break

        power_score = min(len(power_hits) * 8, 20)
        score += power_score
        if power_hits:
            factors.append({"factor": "power_words", "impact": f"+{power_score}", "detail": f"Contains: {power_hits}"})
        else:
            factors.append({"factor": "power_words", "impact": "0", "detail": "No power words — add urgency or value"})

        # Personalization
        if any(w in subject_lower for w in ["you", "your"]):
            score += 8
            factors.append({"factor": "personalization", "impact": "+8", "detail": "Contains personal pronoun"})

        # Emoji (1 emoji = good, 2+ = spammy)
        emoji_count = sum(1 for c in subject if ord(c) > 127)
        if emoji_count == 1:
            score += 5
            factors.append({"factor": "emoji", "impact": "+5", "detail": "1 emoji — good attention grabber"})
        elif emoji_count > 2:
            score -= 10
            factors.append({"factor": "emoji", "impact": "-10", "detail": f"{emoji_count} emojis — looks spammy"})

        # Spam triggers
        spam_words = ["buy now", "act now", "click here", "!!!!", "$$", "100% free", "winner"]
        spam_count = sum(1 for w in spam_words if w in subject_lower)
        if spam_count:
            score -= spam_count * 10
            factors.append({"factor": "spam_risk", "impact": f"-{spam_count * 10}", "detail": f"{spam_count} spam trigger words"})

        # Number/statistic (increases curiosity)
        if any(c.isdigit() for c in subject):
            score += 5
            factors.append({"factor": "number", "impact": "+5", "detail": "Contains number — increases specificity"})

        # Question (increases open rate)
        if "?" in subject:
            score += 5
            factors.append({"factor": "question", "impact": "+5", "detail": "Question format — triggers curiosity"})

        score = max(0, min(100, score))

        return {
            "subject": subject,
            "score": score,
            "grade": "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "F",
            "factors": factors,
            "predicted_open_rate": self._predict_open_rate(score),
            "improvements": self._suggest_improvements(subject, factors, power_hits),
        }

    def optimal_send_time(self, customer: dict[str, Any], engagement_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Calculate optimal send time for a specific customer."""
        timezone_offset = int(customer.get("timezone_offset", 0))

        if engagement_history:
            # Find when this customer actually opens emails
            open_hours = [h.get("hour", 10) for h in engagement_history if h.get("action") == "open"]
            if open_hours:
                # Mode (most common hour)
                hour_counts: dict[int, int] = {}
                for h in open_hours:
                    hour_counts[h] = hour_counts.get(h, 0) + 1
                best_hour = max(hour_counts, key=hour_counts.get)
                return {
                    "optimal_hour_utc": (best_hour - timezone_offset) % 24,
                    "optimal_hour_local": best_hour,
                    "method": "personalized",
                    "confidence": "high" if len(open_hours) >= 5 else "medium",
                    "data_points": len(open_hours),
                }

        # Default: use day-of-week optimal times
        import time
        day = time.localtime().tm_wday
        default_hour = OPTIMAL_SEND_HOURS.get(day, 10)

        return {
            "optimal_hour_utc": (default_hour - timezone_offset) % 24,
            "optimal_hour_local": default_hour,
            "method": "default",
            "confidence": "low",
            "recommendation": "Collect more engagement data for personalized timing",
        }

    def build_automation_flow(self, flow_type: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build automated email flow for Shopify store."""
        flows = {
            "welcome": self._welcome_flow,
            "abandoned_cart": self._abandoned_cart_flow,
            "post_purchase": self._post_purchase_flow,
            "win_back": self._win_back_flow,
            "browse_abandonment": self._browse_abandonment_flow,
            "vip": self._vip_flow,
        }

        builder = flows.get(flow_type)
        if builder is None:
            return {"error": f"Unknown flow: {flow_type}", "available": list(flows.keys())}

        return builder(config or {})

    def _welcome_flow(self, config: dict) -> dict:
        return {
            "name": "Welcome Series",
            "trigger": "customer.created",
            "emails": [
                {"delay": "0h", "subject": "Welcome to {store_name}! Here's 10% off your first order", "type": "welcome", "include_discount": True},
                {"delay": "24h", "subject": "Our bestsellers — picked for you", "type": "product_showcase", "products": "bestsellers"},
                {"delay": "72h", "subject": "Your {store_name} guide — everything you need to know", "type": "brand_story"},
                {"delay": "168h", "subject": "Your 10% off expires tomorrow ⏰", "type": "urgency_reminder", "include_discount": True},
            ],
            "exit_condition": "customer.placed_order",
            "estimated_conversion": "15-25%",
        }

    def _abandoned_cart_flow(self, config: dict) -> dict:
        return {
            "name": "Abandoned Cart Recovery",
            "trigger": "checkout.abandoned",
            "emails": [
                {"delay": "1h", "subject": "You left something behind...", "type": "cart_reminder", "include_cart_items": True},
                {"delay": "24h", "subject": "Still thinking it over? Here's free shipping 🚚", "type": "incentive", "offer": "free_shipping"},
                {"delay": "72h", "subject": "Last chance — your cart expires soon", "type": "urgency", "include_discount": True, "discount": "10%"},
            ],
            "exit_condition": "order.created",
            "estimated_recovery": "5-15%",
        }

    def _post_purchase_flow(self, config: dict) -> dict:
        return {
            "name": "Post-Purchase",
            "trigger": "order.fulfilled",
            "emails": [
                {"delay": "24h", "subject": "How to get the most from your {product_name}", "type": "onboarding"},
                {"delay": "168h", "subject": "How's your {product_name}? We'd love your feedback", "type": "review_request"},
                {"delay": "336h", "subject": "Based on your purchase — you might love these", "type": "cross_sell", "products": "related"},
                {"delay": "720h", "subject": "Time for a restock? 🔄", "type": "replenishment"},
            ],
            "exit_condition": None,
            "estimated_repeat_rate": "20-30%",
        }

    def _win_back_flow(self, config: dict) -> dict:
        days = int(config.get("inactive_days", 90))
        return {
            "name": "Win-Back",
            "trigger": f"customer.inactive_{days}d",
            "emails": [
                {"delay": "0h", "subject": "We miss you! Here's 15% off to come back", "type": "win_back", "discount": "15%"},
                {"delay": "168h", "subject": "See what's new since you've been gone", "type": "new_arrivals"},
                {"delay": "336h", "subject": "Final offer: 20% off — just for you", "type": "last_chance", "discount": "20%"},
            ],
            "exit_condition": "order.created",
            "estimated_recovery": "3-8%",
        }

    def _browse_abandonment_flow(self, config: dict) -> dict:
        return {
            "name": "Browse Abandonment",
            "trigger": "session.viewed_product_no_cart",
            "emails": [
                {"delay": "2h", "subject": "Still interested in {product_name}?", "type": "product_reminder"},
                {"delay": "48h", "subject": "Trending now: {product_name} is selling fast", "type": "social_proof"},
            ],
            "exit_condition": "cart.created",
            "estimated_conversion": "2-5%",
        }

    def _vip_flow(self, config: dict) -> dict:
        return {
            "name": "VIP Program",
            "trigger": "customer.total_spent > 500",
            "emails": [
                {"delay": "0h", "subject": "You're officially VIP! 🌟 Here's your exclusive perks", "type": "vip_welcome"},
                {"delay": "168h", "subject": "VIP early access: new collection drops tomorrow", "type": "early_access"},
                {"delay": "720h", "subject": "Happy anniversary! A special gift for our VIP", "type": "anniversary"},
            ],
            "exit_condition": None,
            "estimated_ltv_increase": "40-60%",
        }

    @staticmethod
    def _predict_open_rate(score: int) -> str:
        if score >= 80: return "25-35% (excellent)"
        if score >= 65: return "20-25% (good)"
        if score >= 50: return "15-20% (average)"
        if score >= 35: return "10-15% (below average)"
        return "<10% (poor)"

    @staticmethod
    def _suggest_improvements(subject: str, factors: list, power_hits: dict) -> list[str]:
        improvements = []
        if len(subject) > 50:
            improvements.append(f"Shorten to under 50 characters (currently {len(subject)})")
        if "urgency" not in power_hits:
            improvements.append("Add urgency: 'today only', 'last chance', 'ending soon'")
        if "value" not in power_hits:
            improvements.append("Add value trigger: 'free', 'save', 'exclusive'")
        if not any(c.isdigit() for c in subject):
            improvements.append("Add a specific number: '20% off', '3 new arrivals', '48 hours left'")
        if "your" not in subject.lower() and "you" not in subject.lower():
            improvements.append("Personalize: use 'you' or 'your'")
        return improvements[:3]
