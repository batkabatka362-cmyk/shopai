"""Social trends domain knowledge — expert social commerce intelligence.

What veterans know:
  - "TikTok trends have a 2-4 week product window before saturation"
  - "Instagram Reels trends last longer than TikTok — 4-8 weeks"
  - "Pinterest trends are most sustainable — search-driven, 3-6 month shelf life"
  - "If it's not on Pinterest, the trend probably won't last"
  - "A product going viral doesn't mean it's profitable to sell"
"""
from __future__ import annotations
from typing import Any


PLATFORM_STRATEGIES = {
    "tiktok": {
        "trend_window": "2-4 weeks from first viral video",
        "content_approach": "UGC-style, authentic, unpolished. 15-60 second videos.",
        "creator_strategy": "Partner with 5-10 micro-creators (10k-100k followers) simultaneously",
        "ad_strategy": "Spark Ads on organic viral content; $50-200/day test budget",
        "product_fit": "Under $50, visually interesting, 'wow factor', easy to demonstrate",
        "timing": "Must source product within 48-72 hours of viral detection",
        "pitfalls": [
            "Product sells out before you can source it",
            "Trend dies before your inventory arrives",
            "Copycats flood the market within days",
            "Single viral video ≠ sustained demand",
        ],
    },
    "instagram": {
        "trend_window": "4-8 weeks from Reels virality",
        "content_approach": "Polished Reels for discovery, carousel posts for education, Stories for conversion",
        "creator_strategy": "Mix of micro (10k-100k) and mid-tier (100k-500k) creators",
        "ad_strategy": "Retarget Reels viewers with shopping ads; use saves as intent signal",
        "product_fit": "$20-$150, aesthetically pleasing, lifestyle integration",
        "timing": "Can move slightly slower than TikTok — 1 week from detection is OK",
        "pitfalls": [
            "Instagram saves don't always convert to purchases",
            "Algorithm deprioritizes overly commercial content",
            "Reels are often TikTok reposts — check if TikTok already peaked",
        ],
    },
    "pinterest": {
        "trend_window": "3-6 months of sustained search traffic",
        "content_approach": "High-quality vertical images, SEO-optimized descriptions, rich pins",
        "creator_strategy": "Focus on SEO, not creators. Idea Pins for reach, product pins for conversion",
        "ad_strategy": "Shopping ads with direct product links; low CPC ($0.10-$0.50)",
        "product_fit": "$30-$200, home/fashion/wedding/DIY, visually aspirational",
        "timing": "Longer runway — can take 2-4 weeks to set up and still capture demand",
        "pitfalls": [
            "Slow to build — requires patience",
            "Male demographic underrepresented",
            "High purchase intent but lower volume than TikTok/Instagram",
        ],
    },
    "youtube": {
        "trend_window": "2-12 months depending on content type",
        "content_approach": "Review/comparison long-form (8-15 min), Shorts for awareness",
        "creator_strategy": "Sponsor 2-3 mid-tier reviewers in your niche for credibility",
        "ad_strategy": "Pre-roll on competitor review videos; $100-500/day for high-ticket",
        "product_fit": "$50+, complex/considered purchases, tech, fitness equipment",
        "timing": "Longer sales cycle — 2-4 weeks from video to purchase decision",
        "pitfalls": [
            "Expensive creator partnerships",
            "Long production timelines for quality content",
            "Returns can be high if product doesn't match review expectations",
        ],
    },
}

SOCIAL_HEURISTICS = [
    "TikTok trends have a 2-4 week product window — if you can't source in 72 hours, you're probably too late",
    "Instagram Reels trends last longer than TikTok — 4-8 weeks — giving more runway",
    "Pinterest trends are the most sustainable because they're search-driven, not algorithm-driven",
    "A product with 10M TikTok views but 0 Pinterest saves = likely a fad, not a trend",
    "Multi-platform virality (3+ platforms) = real demand; single-platform = possible algorithm artifact",
    "Micro-creator virality is stronger signal than mega-creator — organic vs paid",
    "#TikTokMadeMeBuyIt videos with 'honest review' outperform pure hype 3:1 for conversions",
    "Instagram saves are the strongest purchase intent signal on that platform",
    "Pinterest click-through to product page = bottom-of-funnel intent, highest conversion rate",
    "YouTube review videos create sustained demand for months — best for high-ticket items",
    "If a product goes viral on TikTok, check Amazon BSR within 24 hours for demand confirmation",
    "Entertainment virality ≠ product opportunity — dancing + product in background is noise",
    "Products that solve a visible problem ('before/after') go viral more sustainably than novelty items",
    "Seasonal social trends (e.g., summer gadgets) repeat annually — time your inventory",
    "Don't chase virality from a single creator post — wait for multiple creators organically",
]

# When social trend = product opportunity vs just entertainment
OPPORTUNITY_SIGNALS = {
    "strong_product_opportunity": [
        "Multiple creators independently featuring the product",
        "Comments asking 'where can I buy this?'",
        "Hashtags include #musthave, #tiktokmademebuyit, #amazonfinds",
        "Product solves a visible problem (before/after content)",
        "Cross-platform pickup within 7 days",
        "Pinterest pins appearing alongside TikTok virality",
    ],
    "likely_entertainment_only": [
        "Single creator with single viral video",
        "Product is a prop, not the focus of the content",
        "Comments are about the creator/humor, not the product",
        "No purchase-intent hashtags present",
        "Trend is a dance/meme/challenge that happens to include a product",
        "No Amazon BSR movement despite high view counts",
    ],
    "ambiguous_needs_monitoring": [
        "2-3 creators but all in same niche/friend group",
        "High views but low saves/shares (passive consumption)",
        "Product is interesting but unclear if demand is real",
        "Viral on TikTok only — waiting for cross-platform confirmation",
    ],
}


def get_platform_strategy(platform: str) -> dict[str, Any]:
    """Get expert strategy for a specific platform."""
    return PLATFORM_STRATEGIES.get(platform.lower(), PLATFORM_STRATEGIES["tiktok"])


def get_heuristics() -> list[str]:
    """Get social commerce expert heuristics."""
    return SOCIAL_HEURISTICS


def get_opportunity_signals(signal_type: str = "strong_product_opportunity") -> list[str]:
    """Get signals that distinguish product opportunities from entertainment."""
    return OPPORTUNITY_SIGNALS.get(signal_type, [])


def is_product_opportunity(indicators: dict[str, bool]) -> dict[str, Any]:
    """Quick assessment: is this viral content a product opportunity?

    indicators: dict of signal names -> True/False
    """
    strong_signals = OPPORTUNITY_SIGNALS["strong_product_opportunity"]
    entertainment_signals = OPPORTUNITY_SIGNALS["likely_entertainment_only"]

    strong_count = sum(1 for s in strong_signals if indicators.get(s, False))
    entertainment_count = sum(1 for s in entertainment_signals if indicators.get(s, False))

    total_checked = sum(1 for v in indicators.values() if isinstance(v, bool))
    if total_checked == 0:
        return {"verdict": "unknown", "reason": "No indicators provided"}

    if strong_count >= 3 and entertainment_count <= 1:
        return {
            "verdict": "product_opportunity",
            "confidence": min(0.95, 0.5 + strong_count * 0.1),
            "reason": f"{strong_count} strong product signals detected",
        }
    elif entertainment_count >= 3 and strong_count <= 1:
        return {
            "verdict": "entertainment_only",
            "confidence": min(0.90, 0.4 + entertainment_count * 0.1),
            "reason": f"{entertainment_count} entertainment-only signals detected",
        }
    else:
        return {
            "verdict": "ambiguous",
            "confidence": 0.3,
            "reason": f"Mixed signals — {strong_count} product, {entertainment_count} entertainment",
        }
