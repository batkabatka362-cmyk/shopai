"""Traffic-source specific landing page recommendations."""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.customer.landing_pages")

# Traffic source -> optimal landing page type
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


def recommend_landing_pages() -> dict[str, Any]:
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
