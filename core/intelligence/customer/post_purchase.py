"""Post-purchase experience sequence planning."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.customer.post_purchase")

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


def get_post_purchase_plan() -> dict[str, Any]:
    """Get the post-purchase experience sequence."""
    return {
        "sequence": POST_PURCHASE_SEQUENCE,
        "key_insight": "Post-purchase experience determines LTV more than acquisition. "
                      "A customer who gets a review request on day 7 is 3x more likely to leave one "
                      "than one who gets it on day 30.",
    }
