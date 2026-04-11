"""
knowledge.py — Curated insights and actionable wisdom about reviews.

Use get_insight(key) for a single insight, get_insights_for_stage(stage)
for phase-appropriate advice, or get_all_actionable_tips() for a flat list.
"""


# ---------------------------------------------------------------------------
# Core review insights — keyed for quick lookup
# ---------------------------------------------------------------------------

REVIEW_INSIGHTS = {
    # Strategic framing
    "one_star_roadmap": {
        "insight": "1-star reviews are your product roadmap.",
        "detail": (
            "Every competitor's worst reviews reveal exactly what customers want "
            "and aren't getting. Read them systematically — each complaint is a "
            "feature request for your product."
        ),
        "stage": "research",
        "impact": "high",
    },
    "photo_reviews_convert": {
        "insight": "Photo reviews convert 4.5x better than text-only reviews.",
        "detail": (
            "Shoppers trust what they can see. A single photo review is worth "
            "more than five text-only reviews for conversion. Incentivize photo "
            "submissions in every post-purchase touchpoint."
        ),
        "stage": "growth",
        "impact": "high",
    },
    "first_ten_hardest": {
        "insight": "First 10 reviews are hardest — use post-purchase email.",
        "detail": (
            "Going from 0 to 10 reviews is the steepest climb. Automate a "
            "post-purchase email sequence: day 7 check-in, day 14 review "
            "request. Make it personal, not transactional."
        ),
        "stage": "launch",
        "impact": "critical",
    },
    "competitor_weakness_usp": {
        "insight": "Competitor's weakness = your USP.",
        "detail": (
            "If competitors consistently get complaints about durability, make "
            "durability your headline. Turn their recurring 1-star themes into "
            "your unique selling proposition and say it loudly."
        ),
        "stage": "research",
        "impact": "high",
    },
    # Conversion and trust
    "social_proof_threshold": {
        "insight": "Products with 50+ reviews see a measurable conversion lift.",
        "detail": (
            "Conversion rate increases sharply from 0 to 10 reviews, then "
            "steadily climbs until around 50. After 50, the marginal gain per "
            "review decreases but cumulative trust keeps compounding."
        ),
        "stage": "growth",
        "impact": "high",
    },
    "negative_reviews_help": {
        "insight": "A few negative reviews actually increase trust.",
        "detail": (
            "Products with a perfect 5.0 rating convert worse than those with "
            "4.2-4.7. Shoppers are suspicious of perfection. A handful of "
            "honest 3-star reviews makes the 5-stars more believable."
        ),
        "stage": "compete",
        "impact": "medium",
    },
    "review_recency_matters": {
        "insight": "Recent reviews matter more than total count.",
        "detail": (
            "A product with 50 reviews in the last month outperforms one with "
            "500 reviews but none recent. Shoppers check dates. Keep the "
            "review engine running — consistency beats volume."
        ),
        "stage": "compete",
        "impact": "high",
    },
    # Tactical advice
    "respond_to_negatives": {
        "insight": "Responding to negative reviews can recover 33% of unhappy customers.",
        "detail": (
            "A thoughtful public response shows future buyers you care. Offer a "
            "solution, not excuses. Many reviewers will update their rating after "
            "a genuine resolution."
        ),
        "stage": "growth",
        "impact": "medium",
    },
    "review_velocity_signal": {
        "insight": "Review velocity signals product-market fit to algorithms.",
        "detail": (
            "Marketplace search algorithms factor in review velocity. A steady "
            "stream of reviews tells the algorithm your product is active and "
            "popular, boosting organic ranking."
        ),
        "stage": "growth",
        "impact": "high",
    },
    "verified_purchase_weight": {
        "insight": "Verified purchase reviews carry 2-3x more algorithmic weight.",
        "detail": (
            "Platforms give more visibility to verified purchase reviews. Focus "
            "on converting actual buyers into reviewers rather than seeding "
            "unverified reviews."
        ),
        "stage": "launch",
        "impact": "high",
    },
    "ugc_flywheel": {
        "insight": "Turn reviews into ads — the UGC flywheel.",
        "detail": (
            "Screenshot great reviews and use them in social ads. This creates "
            "a flywheel: reviews drive sales, sales create more reviews, and "
            "the cycle accelerates."
        ),
        "stage": "compete",
        "impact": "medium",
    },
    "star_rating_in_ads": {
        "insight": "Showing star ratings in ad creative lifts CTR by up to 17%.",
        "detail": (
            "Once you have a strong average rating (4.3+), feature it "
            "prominently in every ad. Star ratings are a universal trust "
            "shortcut that shoppers process instantly."
        ),
        "stage": "compete",
        "impact": "medium",
    },
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_insight(key):
    """Return a single insight dict by key, or None if not found."""
    return REVIEW_INSIGHTS.get(key)


def get_insights_for_stage(stage):
    """Return all insights relevant to a business stage.

    Stages: 'launch', 'growth', 'compete', 'research'
    """
    return [
        {"key": k, **v}
        for k, v in REVIEW_INSIGHTS.items()
        if v.get("stage") == stage
    ]


def get_all_actionable_tips():
    """Return a flat list of one-line insight strings for quick reference."""
    return [v["insight"] for v in REVIEW_INSIGHTS.values()]


def get_high_impact_insights():
    """Return only high or critical impact insights."""
    return [
        {"key": k, **v}
        for k, v in REVIEW_INSIGHTS.items()
        if v.get("impact") in ("high", "critical")
    ]


def get_insight_summary():
    """Return a compact summary: key -> one-line insight."""
    return {k: v["insight"] for k, v in REVIEW_INSIGHTS.items()}
