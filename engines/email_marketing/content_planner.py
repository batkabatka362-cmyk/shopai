"""Email Marketing Engine — content planner.

Plans the email content structure: header, hero image, body sections, CTA,
and footer. Adapts structure based on campaign type (promotional, nurture,
win-back, announcement).

No model — pure deterministic planning.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Section templates per campaign type
# ---------------------------------------------------------------------------

_CAMPAIGN_STRUCTURES: dict[str, list[dict[str, str]]] = {
    "promotional": [
        {"type": "header", "purpose": "brand logo + navigation", "notes": "keep minimal"},
        {"type": "hero", "purpose": "hero image with discount banner", "notes": "bold, eye-catching"},
        {"type": "offer", "purpose": "primary discount/offer details", "notes": "clear value proposition"},
        {"type": "products", "purpose": "featured product grid", "notes": "max 3-4 products with images"},
        {"type": "social_proof", "purpose": "reviews or trust badges", "notes": "1-2 testimonials"},
        {"type": "cta", "purpose": "primary call to action", "notes": "shop now button, urgent language"},
        {"type": "footer", "purpose": "unsubscribe + legal", "notes": "CAN-SPAM compliant"},
    ],
    "nurture": [
        {"type": "header", "purpose": "brand logo + warm greeting", "notes": "personal tone"},
        {"type": "story", "purpose": "educational or brand story content", "notes": "value-first, no hard sell"},
        {"type": "tips", "purpose": "helpful tips or how-to content", "notes": "actionable advice"},
        {"type": "soft_cta", "purpose": "gentle call to action", "notes": "learn more, explore"},
        {"type": "footer", "purpose": "unsubscribe + social links", "notes": "friendly sign-off"},
    ],
    "win-back": [
        {"type": "header", "purpose": "brand logo + we miss you", "notes": "emotional hook"},
        {"type": "hero", "purpose": "re-engagement hero image", "notes": "warm, inviting"},
        {"type": "incentive", "purpose": "special comeback offer", "notes": "exclusive discount or freebie"},
        {"type": "whats_new", "purpose": "highlight new products or changes", "notes": "show what they missed"},
        {"type": "cta", "purpose": "come back and shop", "notes": "strong urgency, limited time"},
        {"type": "footer", "purpose": "unsubscribe + preference center", "notes": "easy opt-down option"},
    ],
    "announcement": [
        {"type": "header", "purpose": "brand logo + announcement badge", "notes": "newsworthy feel"},
        {"type": "headline", "purpose": "big announcement headline", "notes": "clear, exciting"},
        {"type": "details", "purpose": "announcement body with details", "notes": "concise, scannable"},
        {"type": "visual", "purpose": "supporting image or graphic", "notes": "relevant to announcement"},
        {"type": "cta", "purpose": "learn more or take action", "notes": "contextual CTA"},
        {"type": "footer", "purpose": "unsubscribe + legal", "notes": "standard compliance"},
    ],
}

_CTA_STRATEGIES: dict[str, str] = {
    "promotional": "urgency-driven: 'Shop Now — Sale Ends Soon'",
    "nurture": "value-driven: 'Learn More' or 'Explore'",
    "win-back": "incentive-driven: 'Claim Your Offer' with countdown",
    "announcement": "curiosity-driven: 'See What's New' or 'Get Started'",
}

_TONES: dict[str, str] = {
    "promotional": "exciting, urgent, benefit-focused",
    "nurture": "warm, helpful, educational",
    "win-back": "empathetic, enticing, personal",
    "announcement": "confident, newsworthy, clear",
}

_PERSONALIZATION_TOKENS: dict[str, list[str]] = {
    "promotional": ["{{first_name}}", "{{last_purchase_category}}", "{{loyalty_tier}}"],
    "nurture": ["{{first_name}}", "{{interest_area}}", "{{signup_date}}"],
    "win-back": ["{{first_name}}", "{{last_order_date}}", "{{favorite_product}}"],
    "announcement": ["{{first_name}}", "{{city}}"],
}


def plan_content(
    goal: str,
    products: list[dict[str, Any]],
    store_name: str,
    discount: dict[str, Any],
) -> dict[str, Any]:
    """Plan the email content structure based on campaign type.

    Args:
        goal: Campaign goal / type.
        products: List of ProductInfo dicts.
        store_name: Store display name.
        discount: DiscountInfo dict.

    Returns:
        Structured dict with ContentPlan data.
    """
    try:
        goal_key = str(goal).lower().strip()
        prods = copy.deepcopy(products)

        # Resolve structure template
        sections = copy.deepcopy(
            _CAMPAIGN_STRUCTURES.get(goal_key, _CAMPAIGN_STRUCTURES["promotional"])
        )

        # Inject product count context into the products section
        product_count = len(prods) if prods else 0
        for section in sections:
            if section["type"] == "products" and product_count > 0:
                section["notes"] = f"featuring {product_count} product(s) with images and prices"
            if section["type"] in ("offer", "incentive") and discount:
                disc_type = discount.get("type", "percentage")
                disc_val = discount.get("value", 0)
                if disc_type == "percentage":
                    section["notes"] += f" — {disc_val}% off"
                else:
                    section["notes"] += f" — ${disc_val} off"

        cta_strategy = _CTA_STRATEGIES.get(goal_key, _CTA_STRATEGIES["promotional"])
        tone = _TONES.get(goal_key, _TONES["promotional"])
        personalization_tokens = _PERSONALIZATION_TOKENS.get(
            goal_key, _PERSONALIZATION_TOKENS["promotional"]
        )

        return {
            "status": "success",
            "plan": {
                "campaign_type": goal_key,
                "sections": sections,
                "cta_strategy": cta_strategy,
                "tone": tone,
                "personalization_tokens": personalization_tokens,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "plan": {},
            "error": f"Content planning failed: {exc}",
        }
