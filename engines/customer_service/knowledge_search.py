"""Customer Service Engine — knowledge base search.

Searches a built-in set of FAQ articles using keyword overlap scoring
with intent-specific boosting. Returns ranked results.

All logic is real keyword matching. No faking, no random numbers.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Built-in FAQ knowledge base — 15 articles
# ---------------------------------------------------------------------------

_FAQ_ARTICLES: list[dict[str, Any]] = [
    {
        "article_id": "faq_001",
        "title": "Shipping Policy — Domestic Orders",
        "content": (
            "We offer free standard shipping on all domestic orders over $50. "
            "Standard shipping takes 5-7 business days. Express shipping (2-3 business days) "
            "is available for $9.99. Overnight shipping is $19.99. Orders placed before "
            "2 PM EST ship the same day. All orders include tracking numbers sent via email."
        ),
        "tags": ["shipping", "delivery", "free shipping", "express", "overnight", "tracking", "domestic"],
        "intent_boost": ["shipping", "tracking"],
    },
    {
        "article_id": "faq_002",
        "title": "International Shipping",
        "content": (
            "We ship to over 40 countries worldwide. International standard shipping takes "
            "10-21 business days and costs $14.99-$29.99 depending on destination. International "
            "express (5-7 business days) is available for $29.99-$49.99. Customs duties and taxes "
            "are the responsibility of the recipient. Some items may be restricted in certain countries."
        ),
        "tags": ["international", "shipping", "customs", "duties", "worldwide", "global"],
        "intent_boost": ["shipping"],
    },
    {
        "article_id": "faq_003",
        "title": "Return Policy",
        "content": (
            "We accept returns within 30 days of delivery for a full refund. Items must be unused, "
            "in original packaging, and with all tags attached. To start a return, go to My Orders "
            "and select 'Return Item' or contact support. We provide free return shipping labels for "
            "defective items. For non-defective returns, a $5.99 return shipping fee applies. "
            "Exchanges are free of charge."
        ),
        "tags": ["return", "refund", "exchange", "30 days", "return policy", "return label"],
        "intent_boost": ["return_request", "refund_request"],
    },
    {
        "article_id": "faq_004",
        "title": "Refund Processing",
        "content": (
            "Refunds are processed within 3-5 business days after we receive the returned item. "
            "The refund is issued to the original payment method. Credit card refunds may take an "
            "additional 5-10 business days to appear on your statement depending on your bank. "
            "Store credit refunds are applied instantly. For orders paid via PayPal, refunds "
            "appear within 1-2 business days."
        ),
        "tags": ["refund", "money back", "processing", "credit card", "paypal", "store credit"],
        "intent_boost": ["refund_request"],
    },
    {
        "article_id": "faq_005",
        "title": "Payment Methods",
        "content": (
            "We accept Visa, Mastercard, American Express, Discover, PayPal, Apple Pay, "
            "Google Pay, and Shop Pay. We also accept gift cards and store credit. All payments "
            "are processed securely with 256-bit SSL encryption. You can split payment between "
            "a gift card and another payment method. Affirm financing is available for orders "
            "over $50 (subject to approval)."
        ),
        "tags": ["payment", "credit card", "paypal", "apple pay", "gift card", "financing", "billing"],
        "intent_boost": ["billing"],
    },
    {
        "article_id": "faq_006",
        "title": "Sizing Guide",
        "content": (
            "Our sizing guide is available on every product page. We recommend measuring yourself "
            "and comparing to our size chart. If you are between sizes, we recommend sizing up for "
            "a more comfortable fit. Our customer reviews often include sizing feedback. For shoes, "
            "we follow standard US sizing. European and UK size conversions are listed on each "
            "product page. Contact us for specific fit questions."
        ),
        "tags": ["size", "sizing", "fit", "size chart", "measurement", "dimensions"],
        "intent_boost": ["product_question", "return_request"],
    },
    {
        "article_id": "faq_007",
        "title": "Order Tracking",
        "content": (
            "Once your order ships, you will receive a shipping confirmation email with your "
            "tracking number. You can also track your order by logging into your account and "
            "going to My Orders. Click 'Track Package' next to your order. We support tracking "
            "for UPS, FedEx, USPS, and DHL. If your tracking has not updated in 48 hours, "
            "please contact our support team."
        ),
        "tags": ["tracking", "track", "package", "shipping confirmation", "ups", "fedex", "usps", "dhl"],
        "intent_boost": ["tracking", "order_status"],
    },
    {
        "article_id": "faq_008",
        "title": "Order Cancellation",
        "content": (
            "You can cancel your order within 1 hour of placing it, provided it has not already "
            "entered the fulfillment process. To cancel, go to My Orders and select 'Cancel Order'. "
            "If the cancel option is not available, the order is already being prepared and cannot "
            "be cancelled. In that case, you may return the item once received. Refunds for "
            "cancelled orders are processed within 1-2 business days."
        ),
        "tags": ["cancel", "cancellation", "cancel order", "void"],
        "intent_boost": ["order_status", "refund_request"],
    },
    {
        "article_id": "faq_009",
        "title": "Damaged or Defective Items",
        "content": (
            "If you receive a damaged or defective item, please contact us within 7 days of "
            "delivery. Include your order number and photos of the damage. We will send a "
            "replacement at no cost, or issue a full refund including return shipping. Defective "
            "items are covered by our warranty for up to 1 year from purchase. We may request "
            "the item be returned for quality review."
        ),
        "tags": ["damaged", "defective", "broken", "warranty", "replacement", "quality"],
        "intent_boost": ["complaint", "return_request", "refund_request"],
    },
    {
        "article_id": "faq_010",
        "title": "Loyalty Program — Rewards Tiers",
        "content": (
            "Our loyalty program has four tiers: Bronze (0-499 points), Silver (500-1499 points), "
            "Gold (1500-4999 points), and Platinum (5000+ points). Earn 1 point per dollar spent. "
            "Silver members get free standard shipping. Gold members get 10%% off and early access "
            "to sales. Platinum members get 15%% off, free express shipping, and a dedicated "
            "support line. Points expire after 12 months of inactivity."
        ),
        "tags": ["loyalty", "rewards", "points", "tier", "bronze", "silver", "gold", "platinum", "discount"],
        "intent_boost": ["billing", "general"],
    },
    {
        "article_id": "faq_011",
        "title": "Account & Password Help",
        "content": (
            "To reset your password, click 'Forgot Password' on the login page and enter your "
            "email address. You will receive a reset link within 5 minutes. If you do not see "
            "the email, check your spam folder. To update your account details (name, email, "
            "phone), go to Account Settings. To delete your account, please contact support. "
            "We recommend enabling two-factor authentication for added security."
        ),
        "tags": ["account", "password", "login", "reset", "security", "profile", "sign in"],
        "intent_boost": ["general"],
    },
    {
        "article_id": "faq_012",
        "title": "Product Warranty",
        "content": (
            "All products come with a 1-year limited warranty covering manufacturing defects. "
            "Electronics have a 2-year warranty. The warranty does not cover normal wear and tear, "
            "misuse, or accidental damage. To make a warranty claim, contact support with your "
            "order number and a description of the issue. We may request photos or the item to be "
            "returned. Warranty replacements are shipped free of charge."
        ),
        "tags": ["warranty", "guarantee", "defect", "manufacturing", "claim", "coverage"],
        "intent_boost": ["product_question", "complaint"],
    },
    {
        "article_id": "faq_013",
        "title": "Promo Codes & Discounts",
        "content": (
            "Enter your promo code at checkout in the 'Discount Code' field and click Apply. "
            "Only one promo code can be used per order. Promo codes cannot be combined with "
            "other offers unless stated otherwise. If your code is not working, check that it "
            "has not expired and that your order meets the minimum purchase requirement. "
            "Subscribe to our newsletter for exclusive discount codes."
        ),
        "tags": ["promo", "coupon", "discount", "code", "sale", "offer"],
        "intent_boost": ["billing"],
    },
    {
        "article_id": "faq_014",
        "title": "Contact Us & Business Hours",
        "content": (
            "Our customer support team is available Monday through Friday, 8 AM to 8 PM EST, "
            "and Saturday 9 AM to 5 PM EST. We are closed on Sundays and major holidays. "
            "You can reach us via live chat (fastest), email at support@shop.example.com, "
            "or phone at 1-800-555-0199. Average response time: chat 2 minutes, email 4 hours, "
            "phone 5 minutes. Platinum members have access to 24/7 priority support."
        ),
        "tags": ["contact", "hours", "phone", "email", "chat", "support", "business hours"],
        "intent_boost": ["general"],
    },
    {
        "article_id": "faq_015",
        "title": "Gift Cards",
        "content": (
            "Gift cards are available in denominations of $25, $50, $100, and $200. Digital gift "
            "cards are delivered instantly via email. Physical gift cards ship within 1-2 business "
            "days. Gift cards never expire and have no fees. To check your gift card balance, "
            "go to Gift Cards in your account. Gift cards cannot be returned or redeemed for cash "
            "except where required by law."
        ),
        "tags": ["gift card", "gift", "balance", "present"],
        "intent_boost": ["billing", "product_question"],
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_knowledge(
    query: str,
    intent: str,
) -> dict[str, Any]:
    """Search the FAQ knowledge base by keyword overlap with intent boosting.

    Args:
        query: The search query (usually the customer's message).
        intent: The classified primary intent for boosting.

    Returns:
        Structured dict with ranked article results.
    """
    try:
        if not query or not isinstance(query, str):
            return _fail("Query must be a non-empty string")

        query_tokens = _tokenise(query)
        if not query_tokens:
            return {
                "status": "success",
                "results": [],
            }

        scored: list[dict[str, Any]] = []

        for article in _FAQ_ARTICLES:
            score = _score_article(article, query_tokens, intent)
            if score > 0.0:
                scored.append({
                    "article_id": article["article_id"],
                    "title": article["title"],
                    "snippet": _make_snippet(article["content"], query_tokens),
                    "relevance_score": round(score, 3),
                })

        # Sort by relevance descending
        scored.sort(key=lambda a: a["relevance_score"], reverse=True)

        # Return top 5
        results = scored[:5]

        return {
            "status": "success",
            "results": results,
        }
    except Exception as exc:
        return _fail(f"Knowledge search failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "like",
    "through", "after", "over", "between", "out", "up", "down", "off",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "some", "such", "no", "only", "own", "same", "than", "too", "very",
    "just", "because", "if", "when", "where", "how", "what", "which",
    "who", "whom", "this", "that", "these", "those", "i", "me", "my",
    "we", "our", "you", "your", "it", "its", "they", "them", "their",
})


def _tokenise(text: str) -> set[str]:
    """Tokenise text into lowercase words, removing stop words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _score_article(
    article: dict[str, Any],
    query_tokens: set[str],
    intent: str,
) -> float:
    """Score an article against query tokens with intent boosting."""
    # Build article token set from title, content, and tags
    article_text = " ".join([
        article.get("title", ""),
        article.get("content", ""),
        " ".join(article.get("tags", [])),
    ])
    article_tokens = _tokenise(article_text)

    if not article_tokens:
        return 0.0

    # Keyword overlap (Jaccard-like but weighted toward query coverage)
    overlap = query_tokens & article_tokens
    if not overlap:
        return 0.0

    # Query coverage: what fraction of query tokens matched
    query_coverage = len(overlap) / len(query_tokens)

    # Tag match bonus: extra weight if query tokens match tags directly
    tag_tokens = _tokenise(" ".join(article.get("tags", [])))
    tag_overlap = query_tokens & tag_tokens
    tag_bonus = len(tag_overlap) * 0.15

    base_score = query_coverage + tag_bonus

    # Intent-specific boosting
    intent_boosts = article.get("intent_boost", [])
    if intent in intent_boosts:
        base_score *= 1.4

    return min(base_score, 1.0)


def _make_snippet(content: str, query_tokens: set[str], max_len: int = 200) -> str:
    """Extract a relevant snippet from article content around matching words."""
    sentences = re.split(r"(?<=[.!?])\s+", content)

    # Score each sentence by overlap
    best_sentence = ""
    best_score = -1.0
    for sentence in sentences:
        s_tokens = _tokenise(sentence)
        overlap = len(query_tokens & s_tokens)
        if overlap > best_score:
            best_score = overlap
            best_sentence = sentence

    if not best_sentence:
        best_sentence = content

    if len(best_sentence) > max_len:
        return best_sentence[:max_len].rsplit(" ", 1)[0] + "..."
    return best_sentence


def _fail(reason: str) -> dict[str, Any]:
    """Return a standardised error result."""
    return {
        "status": "error",
        "results": [],
        "error": reason,
    }
