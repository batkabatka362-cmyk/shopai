"""Market size domain knowledge — expert benchmarks and heuristics.

What a 10-year e-commerce veteran knows about market sizing:
  - "Pet supplies is growing 15%/year — fastest e-commerce category"
  - "Electronics has huge TAM but margins are thin (15%)"
  - "Health/beauty has highest margins (60%) but heavy competition"
  - "Books is actually declining — don't enter"
  - "Niche > broad: $1M niche with 5% share > $1B market with 0.001% share"
"""
from __future__ import annotations

from typing import Any


# Expert insights per category
CATEGORY_INSIGHTS = {
    "electronics": {
        "opportunity": "medium",
        "insight": "Huge market but razor-thin margins (15%). Dominated by Amazon. "
                   "Success requires niche focus (e.g., gaming accessories, smart home).",
        "ideal_niche": ["gaming accessories", "smart home devices", "phone accessories", "audio equipment"],
        "avoid": ["generic electronics", "commodity items (cables, chargers)"],
        "success_factor": "Brand differentiation and customer service",
    },
    "clothing": {
        "opportunity": "high",
        "insight": "High margins (45%) but extremely competitive. "
                   "Brand and community matter more than price.",
        "ideal_niche": ["sustainable fashion", "plus-size", "workwear", "athleisure"],
        "avoid": ["generic fast fashion", "competing on price alone"],
        "success_factor": "Brand story and community building",
    },
    "health_beauty": {
        "opportunity": "very_high",
        "insight": "Highest margins (60%) and growing 12%/year. "
                   "Customers are loyal — high LTV if product works.",
        "ideal_niche": ["clean beauty", "men's grooming", "supplements", "skincare routine"],
        "avoid": ["regulated categories without compliance", "generic vitamins"],
        "success_factor": "Trust, reviews, and before/after results",
    },
    "pet_supplies": {
        "opportunity": "very_high",
        "insight": "Fastest growing category (15%/year). Pet owners spend emotionally. "
                   "High margins (45%) and excellent repeat purchase rates.",
        "ideal_niche": ["organic pet food", "dog accessories", "pet wellness", "breed-specific"],
        "avoid": ["generic pet food (Amazon dominates)"],
        "success_factor": "Emotional branding — pets are family",
    },
    "sports_outdoors": {
        "opportunity": "high",
        "insight": "Passionate buyers who research heavily. "
                   "Good margins (40%) and high AOV.",
        "ideal_niche": ["yoga/pilates", "camping gear", "cycling", "home gym"],
        "avoid": ["generic fitness equipment (commoditized)"],
        "success_factor": "Content marketing and community (YouTube, Instagram)",
    },
    "home_garden": {
        "opportunity": "high",
        "insight": "Post-COVID boom still strong. Good margins (35%). "
                   "Heavy items = shipping cost challenge.",
        "ideal_niche": ["kitchen gadgets", "home organization", "indoor plants", "smart home"],
        "avoid": ["heavy furniture (shipping kills margins)"],
        "success_factor": "Visual content and lifestyle marketing",
    },
    "food_beverage": {
        "opportunity": "high",
        "insight": "Fastest online growth (18%/year) but complex compliance (FDA). "
                   "Subscription model works very well.",
        "ideal_niche": ["specialty coffee", "healthy snacks", "hot sauce", "protein bars"],
        "avoid": ["perishable items without cold chain", "generic groceries"],
        "success_factor": "Subscription model and sampling",
    },
    "jewelry": {
        "opportunity": "medium",
        "insight": "Highest margins (65%) but trust is critical. "
                   "Customers won't buy expensive jewelry from unknown stores.",
        "ideal_niche": ["personalized jewelry", "minimalist", "sustainable materials"],
        "avoid": ["fine jewelry without brand trust", "costume jewelry (race to bottom)"],
        "success_factor": "Trust signals: reviews, guarantees, social proof",
    },
}

# General market sizing heuristics
HEURISTICS = [
    "A niche with $10K/month SOM and 50% margins is better than $100K/month with 10% margins",
    "If you can't find 10 competitors, the market may not exist yet (too early)",
    "If you find 1000+ competitors, you need very strong differentiation",
    "Markets growing >10%/year forgive mistakes — you grow WITH the market",
    "Declining markets (-2% or worse) require stealing market share — much harder",
    "US-only focus: start here, expand to Canada/UK/Australia after validation",
    "Sub-niche should be specific enough to rank on Google page 1 within 6 months",
]


def get_category_insight(category: str) -> dict[str, Any]:
    """Get expert insight for a category."""
    return CATEGORY_INSIGHTS.get(category, {
        "opportunity": "unknown",
        "insight": "No specific insight available for this category",
        "ideal_niche": [],
        "avoid": [],
        "success_factor": "Research the market deeply before entering",
    })


def get_heuristics() -> list[str]:
    """Get general market sizing heuristics."""
    return HEURISTICS


def recommend_niche(category: str, interests: list[str] | None = None) -> dict[str, Any]:
    """Recommend specific niches within a category."""
    insight = get_category_insight(category)

    recommended = insight.get("ideal_niche", [])
    avoid = insight.get("avoid", [])

    # If interests provided, prioritize matching niches
    if interests:
        interests_lower = [i.lower() for i in interests]
        matching = [n for n in recommended if any(i in n.lower() for i in interests_lower)]
        if matching:
            recommended = matching + [n for n in recommended if n not in matching]

    return {
        "category": category,
        "recommended_niches": recommended,
        "avoid_niches": avoid,
        "success_factor": insight.get("success_factor", ""),
        "opportunity_level": insight.get("opportunity", "unknown"),
    }
