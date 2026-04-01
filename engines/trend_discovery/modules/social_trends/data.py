"""Social trends data — platform benchmarks and virality thresholds."""
from __future__ import annotations
from typing import Any


# Engagement rate benchmarks by platform (% of followers/views)
PLATFORM_BENCHMARKS = {
    "tiktok": {
        "engagement_rate": {"low": 3.0, "average": 6.0, "good": 10.0, "viral": 20.0},
        "share_rate": {"low": 0.5, "average": 1.5, "good": 3.0, "viral": 8.0},
        "avg_watch_time_pct": {"low": 20, "average": 40, "good": 60, "viral": 80},
        "content_lifespan_hours": 48,
        "peak_posting_hours": [19, 20, 21, 22],  # 7pm-10pm local
    },
    "instagram": {
        "engagement_rate": {"low": 1.0, "average": 3.0, "good": 6.0, "viral": 12.0},
        "save_rate": {"low": 1.0, "average": 3.0, "good": 7.0, "viral": 15.0},
        "share_rate": {"low": 0.3, "average": 1.0, "good": 2.5, "viral": 6.0},
        "content_lifespan_hours": 72,
        "peak_posting_hours": [11, 12, 17, 18, 19],
    },
    "pinterest": {
        "engagement_rate": {"low": 0.5, "average": 1.5, "good": 3.0, "viral": 8.0},
        "repin_rate": {"low": 1.0, "average": 5.0, "good": 15.0, "viral": 40.0},
        "click_through_rate": {"low": 0.5, "average": 1.5, "good": 3.0, "viral": 6.0},
        "content_lifespan_hours": 4320,  # 6 months
        "peak_posting_hours": [20, 21, 22, 23],
    },
    "youtube": {
        "engagement_rate": {"low": 1.0, "average": 3.5, "good": 7.0, "viral": 15.0},
        "like_rate": {"low": 2.0, "average": 4.0, "good": 8.0, "viral": 15.0},
        "comment_rate": {"low": 0.1, "average": 0.5, "good": 1.5, "viral": 4.0},
        "content_lifespan_hours": 8760,  # 12 months (evergreen)
        "peak_posting_hours": [14, 15, 16, 17],
    },
}

# Virality velocity thresholds — views/hour needed to be considered trending
VIRALITY_VELOCITY = {
    "tiktok": {
        "emerging": 5_000,       # 5k views/hour
        "trending": 50_000,      # 50k views/hour
        "mega_viral": 500_000,   # 500k views/hour
    },
    "instagram": {
        "emerging": 1_000,
        "trending": 10_000,
        "mega_viral": 100_000,
    },
    "youtube": {
        "emerging": 2_000,
        "trending": 20_000,
        "mega_viral": 200_000,
    },
    "pinterest": {
        "emerging": 500,         # pins/hour (slower platform)
        "trending": 5_000,
        "mega_viral": 50_000,
    },
}

# Platform user demographics — median user profile
PLATFORM_DEMOGRAPHICS = {
    "tiktok": {
        "primary_age": "16-34",
        "gender_split": {"female": 57, "male": 43},
        "income_bracket": "lower-mid",
        "purchase_behavior": "impulse, trend-driven, under $50",
        "top_product_categories": ["beauty", "fashion", "gadgets", "food", "fitness"],
    },
    "instagram": {
        "primary_age": "18-40",
        "gender_split": {"female": 52, "male": 48},
        "income_bracket": "mid-upper",
        "purchase_behavior": "aspirational, lifestyle-driven, $20-$150",
        "top_product_categories": ["fashion", "beauty", "home_decor", "travel", "food"],
    },
    "pinterest": {
        "primary_age": "25-50",
        "gender_split": {"female": 76, "male": 24},
        "income_bracket": "mid-upper",
        "purchase_behavior": "planned, research-driven, $30-$200",
        "top_product_categories": ["home_decor", "fashion", "wedding", "diy", "recipes"],
    },
    "youtube": {
        "primary_age": "18-49",
        "gender_split": {"female": 46, "male": 54},
        "income_bracket": "mid",
        "purchase_behavior": "research-heavy, review-influenced, $50+",
        "top_product_categories": ["electronics", "gaming", "beauty", "fitness", "education"],
    },
}

# Hashtag category mapping — which hashtag groups map to product categories
HASHTAG_CATEGORY_MAP = {
    "beauty": ["beautytok", "skincareroutine", "makeuptutorial", "grwm", "beautyhack",
               "skincare", "glowup", "beautyfind"],
    "fashion": ["fashiontok", "ootd", "styleinspo", "thrifthaul", "fashionhaul",
                "outfitideas", "streetstyle"],
    "home": ["hometok", "homedecor", "roomtransformation", "organizationhacks",
             "cleaningtiktok", "kitchengadgets", "homefinds"],
    "fitness": ["fitnesstok", "gymtok", "workoutroutine", "fitnessgadgets",
                "proteinrecipe", "activewear"],
    "food": ["foodtok", "recipetok", "kitchenhacks", "cookingtools",
             "mealprep", "airfryerrecipe"],
    "tech": ["techtok", "gadgetreview", "techfinds", "setupinspo",
             "desksetup", "techhaul"],
}


def get_platform_benchmarks(platform: str) -> dict[str, Any]:
    """Get engagement benchmarks for a specific platform."""
    return PLATFORM_BENCHMARKS.get(platform.lower(), PLATFORM_BENCHMARKS["instagram"])


def get_virality_thresholds(platform: str) -> dict[str, int]:
    """Get virality velocity thresholds for a platform."""
    return VIRALITY_VELOCITY.get(platform.lower(), VIRALITY_VELOCITY["tiktok"])


def get_demographics(platform: str) -> dict[str, Any]:
    """Get user demographics for a platform."""
    return PLATFORM_DEMOGRAPHICS.get(platform.lower(), {})


def get_category_hashtags(category: str) -> list[str]:
    """Get trending hashtags for a product category."""
    return HASHTAG_CATEGORY_MAP.get(category.lower(), [])
