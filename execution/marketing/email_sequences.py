"""Email Sequence Builder — creates automated email flows."""
from __future__ import annotations
from typing import Any
from utils.logger import get_logger
logger = get_logger("email.sequences")


SEQUENCES = {
    "welcome": {
        "emails": [
            {"day": 0, "subject": "Welcome to {store_name}! Here is 15% off",
             "body": "Hi!\n\nThanks for joining {store_name}.\n\nUse code WELCOME15 for 15% off your first order.\n\nBrowse our collection: {store_url}"},
            {"day": 3, "subject": "Our top picks just for you",
             "body": "Hi!\n\nHere are our most popular products:\n\n{top_products}\n\nDon't forget your 15% off code: WELCOME15"},
            {"day": 7, "subject": "Your discount expires soon!",
             "body": "Hi!\n\nYour WELCOME15 code expires in 3 days.\n\nDon't miss out on 15% off: {store_url}"},
        ],
    },
    "abandoned_cart": {
        "emails": [
            {"day": 0, "subject": "You left something behind!",
             "body": "Hi!\n\nYou left {item_name} in your cart.\n\nComplete your order: {cart_url}"},
            {"day": 1, "subject": "Still thinking about it?",
             "body": "Hi!\n\n{item_name} is still waiting for you. Here is 10% off: SAVE10\n\n{cart_url}"},
        ],
    },
    "post_purchase": {
        "emails": [
            {"day": 3, "subject": "How is your {product_name}?",
             "body": "Hi!\n\nWe hope you love your {product_name}!\n\nLeave a review: {review_url}"},
            {"day": 14, "subject": "Products you might love",
             "body": "Hi!\n\nBased on your purchase, you might also like:\n\n{recommendations}"},
        ],
    },
    "win_back": {
        "emails": [
            {"day": 0, "subject": "We miss you! Here is 20% off",
             "body": "Hi!\n\nIt has been a while since your last visit.\n\nUse code COMEBACK20 for 20% off: {store_url}"},
        ],
    },
}


class EmailSequenceBuilder:
    """Creates and manages automated email sequences."""

    def build_sequence(self, sequence_type: str, store_name: str = "Our Store",
                       store_url: str = "", products: list[dict] | None = None) -> dict[str, Any]:
        template = SEQUENCES.get(sequence_type)
        if not template:
            return {"error": "unknown_sequence", "available": list(SEQUENCES.keys())}

        top = ""
        if products:
            top = "\n".join("- {} (${})" .format(
                p.get("title", p.get("name", "")),
                p.get("price", "")) for p in products[:3])

        emails = []
        for e in template["emails"]:
            email = {
                "day": e["day"],
                "subject": e["subject"].format(
                    store_name=store_name, product_name="your product",
                    item_name="your item"),
                "body": e["body"].format(
                    store_name=store_name, store_url=store_url,
                    top_products=top, cart_url=store_url,
                    review_url=store_url, recommendations=top,
                    product_name="your product", item_name="your item"),
            }
            emails.append(email)

        return {
            "sequence": sequence_type,
            "emails": emails,
            "total_emails": len(emails),
            "duration_days": max(e["day"] for e in emails) if emails else 0,
        }

    def build_all(self, store_name: str = "Our Store",
                  store_url: str = "", products: list[dict] | None = None) -> dict[str, Any]:
        all_sequences = {}
        for seq_type in SEQUENCES:
            all_sequences[seq_type] = self.build_sequence(
                seq_type, store_name, store_url, products)
        total_emails = sum(s["total_emails"] for s in all_sequences.values())
        return {
            "sequences": all_sequences,
            "total_sequences": len(all_sequences),
            "total_emails": total_emails,
        }


_instance = None
def get_email_builder():
    global _instance
    if _instance is None:
        _instance = EmailSequenceBuilder()
    return _instance
