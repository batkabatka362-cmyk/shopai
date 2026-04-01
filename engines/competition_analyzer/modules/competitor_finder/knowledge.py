"""
Competitor Finder — Domain Knowledge
Expert heuristics, difficulty rules, discovery strategies, and guidance.
"""
MARKET_DIFFICULTY_RULES = [
    {
        "id": "very_hard_market",
        "condition": "10+ competitors with 4.5+ average rating",
        "verdict": "very_hard",
        "guidance": (
            "This market is extremely competitive. Competitors maintain "
            "excellent customer satisfaction. Differentiation must come from "
            "branding, unique features, or underserved sub-niches."
        ),
    },
    {
        "id": "hard_market_leader_dominance",
        "condition": "Top 3 competitors hold >60% market share",
        "verdict": "hard",
        "guidance": (
            "A few dominant players control most of the revenue. Competing "
            "on price alone is not viable. Look for gaps in their product "
            "lines or customer complaints to exploit."
        ),
    },
    {
        "id": "moderate_market",
        "condition": "5-9 competitors with mixed ratings (3.5-4.5)",
        "verdict": "moderate",
        "guidance": (
            "The market is competitive but not locked down. There is room "
            "for a well-positioned entrant with better quality or pricing."
        ),
    },
    {
        "id": "easy_low_competition",
        "condition": "Fewer than 5 direct competitors with <4.0 avg rating",
        "verdict": "easy",
        "guidance": (
            "Limited competition with room for quality improvement. A strong "
            "product with good reviews can capture share quickly."
        ),
    },
    {
        "id": "beatable_low_reviews",
        "condition": "Competitors with <50 reviews",
        "verdict": "beatable",
        "guidance": (
            "Competitors with fewer than 50 reviews have not built a moat. "
            "A targeted launch campaign can surpass them in weeks."
        ),
    },
    {
        "id": "established_moat",
        "condition": "Store age >3 years with 1000+ reviews",
        "verdict": "entrenched",
        "guidance": (
            "Stores older than 3 years with substantial reviews are deeply "
            "entrenched. Direct competition is costly; consider flanking "
            "strategies or different marketplace channels."
        ),
    },
]

COMPETITIVE_INSIGHTS = {
    "review_velocity": (
        "Review velocity (reviews per month) is a stronger sales signal than "
        "total review count. A product gaining 50 reviews/month is more "
        "threatening than one with 2000 total but only 5/month."
    ),
    "price_anchoring": (
        "The market leader's price sets the anchor. Pricing 15-20% below the "
        "leader can capture price-sensitive shoppers without signaling low quality."
    ),
    "rating_threshold": (
        "Products below 4.0 stars see significant conversion drops. A 4.3+ "
        "rating is the sweet spot where customers feel confident buying."
    ),
    "listing_quality": (
        "Competitors with poor images, thin descriptions, or missing A+ "
        "content are vulnerable even if they have strong sales numbers."
    ),
    "seasonal_patterns": (
        "Some competitors spike during seasonal events (Q4, Prime Day). Their "
        "annual revenue may look strong but steady-state share is lower."
    ),
    "private_label_risk": (
        "If the marketplace itself (e.g., AmazonBasics) sells in your "
        "category, expect aggressive pricing and prominent placement."
    ),
}

COMPETITOR_DISCOVERY_SOURCES = {
    "amazon_search": {
        "name": "Amazon Product Search",
        "method": "Search target keyword on Amazon, collect first 3 pages",
        "reliability": "high",
    },
    "google_shopping": {
        "name": "Google Shopping",
        "method": "Search product keywords in Google Shopping for cross-marketplace view",
        "reliability": "medium",
    },
    "shopify_directories": {
        "name": "Shopify Store Directories",
        "method": "Use myip.ms or BuiltWith to find Shopify stores in the niche",
        "reliability": "medium",
    },
    "marketplace_bestseller_lists": {
        "name": "Marketplace Best Seller Lists",
        "method": "Check category best-seller and new-release lists",
        "reliability": "high",
    },
    "social_media_ads": {
        "name": "Social Media Ad Libraries",
        "method": "Search Facebook Ad Library and TikTok Ad Center for competing ads",
        "reliability": "low",
    },
}


def _find_rule(rule_id):
    """Look up a difficulty rule by its id."""
    for rule in MARKET_DIFFICULTY_RULES:
        if rule["id"] == rule_id:
            return rule
    return MARKET_DIFFICULTY_RULES[2]  # default to moderate


def get_market_difficulty_assessment(direct_count, avg_rating, top3_share_pct):
    """
    Given key metrics, return the best-matching difficulty rule.
    Returns the rule dict or a default moderate assessment.
    """
    if direct_count >= 10 and avg_rating >= 4.5:
        return _find_rule("very_hard_market")
    if top3_share_pct > 60:
        return _find_rule("hard_market_leader_dominance")
    if direct_count < 5 and avg_rating < 4.0:
        return _find_rule("easy_low_competition")
    if 5 <= direct_count <= 9:
        return _find_rule("moderate_market")
    return _find_rule("moderate_market")


def get_competitor_beatable_signals(competitor):
    """
    Evaluate a single competitor and return a list of signals suggesting
    they can be overtaken.
    """
    signals = []
    review_count = competitor.get("review_count", 0)
    rating = competitor.get("rating", 0)
    store_age = competitor.get("store_age_years", 0)
    product_count = competitor.get("product_count", 0)

    if review_count < 50:
        signals.append("Low review count (<50) — no established social proof moat")
    if 0 < rating < 4.0:
        signals.append(f"Below-average rating ({rating}) — customers are dissatisfied")
    if store_age < 1.0:
        signals.append("New store (<1 year) — still building trust and processes")
    if product_count <= 1:
        signals.append("Single-product store — limited brand loyalty or cross-sell")
    if store_age > 3 and review_count < 100:
        signals.append("Old store with few reviews — likely stagnant or declining")

    return signals


def get_discovery_strategy(marketplace):
    """Return recommended competitor discovery sources for a given marketplace."""
    ml = marketplace.lower().strip()
    source_map = {
        "amazon": ["amazon_search", "marketplace_bestseller_lists"],
        "shopify": ["shopify_directories", "google_shopping"],
    }
    keys = next((v for k, v in source_map.items() if k in ml), ["google_shopping", "marketplace_bestseller_lists"])
    return [COMPETITOR_DISCOVERY_SOURCES[k] for k in keys + ["social_media_ads"]]
