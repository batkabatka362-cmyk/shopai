"""Email segmentation — segmented campaigns drive 760% more revenue than broadcast."""
from __future__ import annotations

from typing import Any


def recommend_email_segments(customers: list[dict[str, Any]]) -> dict[str, Any]:
    """Recommend email segments — segmented campaigns drive 760% more revenue than broadcast."""
    segments = {
        "vip": {"criteria": "Top 10% by spend", "frequency": "Weekly exclusive offers", "tone": "Premium, exclusive"},
        "active_buyers": {"criteria": "Purchased in last 30 days", "frequency": "Bi-weekly", "tone": "Helpful, product tips"},
        "at_risk": {"criteria": "No purchase in 60-90 days", "frequency": "Weekly winback", "tone": "We miss you, incentive"},
        "lapsed": {"criteria": "No purchase in 90+ days", "frequency": "Monthly", "tone": "Last chance, big incentive"},
        "new_subscribers": {"criteria": "Email only, no purchase", "frequency": "Welcome series (5 emails)", "tone": "Educational, trust-building"},
        "cart_abandoners": {"criteria": "Added to cart, didn't buy", "frequency": "3-email sequence over 48h", "tone": "Reminder, then urgency"},
        "browse_abandoners": {"criteria": "Viewed product, didn't add to cart", "frequency": "1-2 emails over 7 days", "tone": "Soft reminder, social proof"},
    }

    return {
        "segments": segments,
        "total_segments": len(segments),
        "key_insight": "Segmented email campaigns generate 760% more revenue than one-size-fits-all. "
                      "Start with VIP + at-risk segments for highest immediate impact.",
        "priority_order": ["cart_abandoners", "vip", "at_risk", "new_subscribers", "active_buyers", "lapsed", "browse_abandoners"],
    }
