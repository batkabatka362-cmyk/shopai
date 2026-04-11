"""
logic.py — Strategic logic for turning review data into action.

Functions:
    extract_product_opportunities(complaints) — what to improve in your product
    assess_review_moat(competitor) — how hard it is to match their review count
    recommend_review_strategy(our_position) — how to build reviews fast
"""


def extract_product_opportunities(complaints):
    """Turn competitor complaint data into ranked product improvement opportunities.

    Args:
        complaints: dict of complaint category -> {count, examples}
                    as produced by code._extract_complaints

    Returns:
        list of opportunity dicts sorted by priority score (highest first).
    """
    if not complaints:
        return []

    total_complaints = sum(cat["count"] for cat in complaints.values())
    if total_complaints == 0:
        return []

    priority_weights = {
        "quality_issues": 1.5,
        "not_as_described": 1.4,
        "sizing_fit": 1.2,
        "shipping_problems": 1.0,
        "customer_service": 0.9,
        "packaging": 0.7,
        "other": 0.5,
    }

    opportunities = []
    for category, details in complaints.items():
        weight = priority_weights.get(category, 0.5)
        frequency = details["count"] / total_complaints
        priority_score = round(frequency * weight * 100, 1)

        action = _map_category_to_action(category)
        opportunities.append({
            "category": category,
            "complaint_count": details["count"],
            "frequency_pct": round(frequency * 100, 1),
            "priority_score": priority_score,
            "recommended_action": action,
            "example_complaints": details.get("examples", [])[:2],
        })

    opportunities.sort(key=lambda x: x["priority_score"], reverse=True)
    return opportunities


def _map_category_to_action(category):
    """Map a complaint category to a concrete improvement action."""
    actions = {
        "quality_issues": (
            "Invest in materials and QC. Highlight durability in listings. "
            "Offer satisfaction guarantee to reduce perceived risk."
        ),
        "not_as_described": (
            "Improve product photos with real-life shots. Add precise measurements "
            "and material details. Manage expectations in description."
        ),
        "sizing_fit": (
            "Create detailed size chart with body measurements. Add fit photos on "
            "diverse body types. Consider offering free exchanges."
        ),
        "shipping_problems": (
            "Partner with reliable carriers. Use tracked shipping. Set realistic "
            "delivery windows and send proactive updates."
        ),
        "customer_service": (
            "Build a responsive support system. Respond within 24 hours. "
            "Offer easy returns to turn negatives into repeat buyers."
        ),
        "packaging": (
            "Upgrade packaging to protect products. Consider unboxing experience "
            "as a branding opportunity. Use eco-friendly materials."
        ),
    }
    return actions.get(category, "Investigate further and address root cause.")


def assess_review_moat(competitor):
    """Evaluate how defensible a competitor's review advantage is.

    Args:
        competitor: dict with keys:
            - total_reviews: int
            - average_rating: float
            - review_velocity: dict with reviews_per_month
            - review_quality: dict with photo_review_pct, verified_purchase_pct

    Returns:
        dict with moat_strength, estimated_months_to_match, vulnerabilities
    """
    total = competitor.get("total_reviews", 0)
    rating = competitor.get("average_rating", 0)
    velocity = competitor.get("review_velocity", {}).get("reviews_per_month", 0)
    photo_pct = competitor.get("review_quality", {}).get("photo_review_pct", 0)

    # Moat scoring: 0-100
    count_score = min(total / 10, 30)  # up to 30 points for volume
    rating_score = max((rating - 3.0) * 15, 0)  # up to 30 points for rating
    velocity_score = min(velocity / 2, 20)  # up to 20 points for velocity
    quality_score = min(photo_pct / 5, 20)  # up to 20 points for quality

    moat_score = round(count_score + rating_score + velocity_score + quality_score, 1)
    moat_score = min(moat_score, 100)

    if moat_score >= 70:
        strength = "strong"
    elif moat_score >= 40:
        strength = "moderate"
    else:
        strength = "weak"

    # Estimate months to match assuming aggressive strategy of 15-25 reviews/month
    our_target_velocity = 20
    months_to_match = round(total / our_target_velocity, 1) if our_target_velocity > 0 else 999

    vulnerabilities = _find_review_vulnerabilities(competitor)

    return {
        "moat_score": moat_score,
        "moat_strength": strength,
        "estimated_months_to_match": months_to_match,
        "vulnerabilities": vulnerabilities,
        "breakdown": {
            "volume_score": round(count_score, 1),
            "rating_score": round(rating_score, 1),
            "velocity_score": round(velocity_score, 1),
            "quality_score": round(quality_score, 1),
        },
    }


def _find_review_vulnerabilities(competitor):
    """Identify weak spots in a competitor's review profile."""
    vulns = []
    rating = competitor.get("average_rating", 5)
    photo_pct = competitor.get("review_quality", {}).get("photo_review_pct", 100)
    verified_pct = competitor.get("review_quality", {}).get("verified_purchase_pct", 100)
    trust = competitor.get("trust_score", {}).get("trust_score_pct", 100)
    velocity = competitor.get("review_velocity", {}).get("reviews_per_month", 999)

    if rating < 4.0:
        vulns.append("Below 4-star average signals product issues you can exploit.")
    if photo_pct < 10:
        vulns.append("Low photo review rate suggests less engaged buyers.")
    if verified_pct < 70:
        vulns.append("Low verified purchase rate may indicate incentivized reviews.")
    if trust < 70:
        vulns.append("Low trust score — potential fake reviews undermine credibility.")
    if velocity < 5:
        vulns.append("Slow review velocity — competitor is not growing social proof.")
    return vulns


def recommend_review_strategy(our_position):
    """Generate a review-building strategy based on our current standing.

    Args:
        our_position: dict with keys:
            - our_review_count: int
            - our_avg_rating: float
            - competitor_review_count: int
            - competitor_avg_rating: float
            - category: str

    Returns:
        dict with phase, tactics, timeline, and priority_actions
    """
    our_count = our_position.get("our_review_count", 0)
    our_rating = our_position.get("our_avg_rating", 0)
    comp_count = our_position.get("competitor_review_count", 0)

    if our_count < 10:
        phase = "launch"
    elif our_count < 50:
        phase = "growth"
    elif our_count < comp_count * 0.5:
        phase = "catch_up"
    else:
        phase = "compete"

    tactics = _get_phase_tactics(phase)
    timeline = _estimate_timeline(our_count, comp_count)

    gap = comp_count - our_count
    priority_actions = []
    if our_count < 10:
        priority_actions.append("Send post-purchase email sequence to every buyer.")
        priority_actions.append("Include review request card in packaging.")
        priority_actions.append("Offer product to 5-10 micro-influencers for honest reviews.")
    if our_rating < 4.0 and our_count > 5:
        priority_actions.append("Fix product issues before scaling — bad reviews compound.")
    if gap > 100:
        priority_actions.append("Run a product sampling campaign to accelerate reviews.")
        priority_actions.append("Use Amazon Vine or platform review programs if eligible.")
    if our_rating >= 4.3:
        priority_actions.append("Highlight star rating in ads — social proof converts.")

    return {
        "phase": phase,
        "tactics": tactics,
        "timeline": timeline,
        "priority_actions": priority_actions,
        "review_gap": gap,
    }


def _get_phase_tactics(phase):
    """Return tactics appropriate for the current review-building phase."""
    all_tactics = {
        "launch": [
            "Post-purchase email at day 7 and day 14 after delivery.",
            "Include a branded review card with QR code in every order.",
            "Seed 5-10 reviews via friends, family, or micro-influencer gifting.",
            "Respond to every review — shows you care and encourages others.",
        ],
        "growth": [
            "A/B test review request timing (day 5 vs day 10 vs day 21).",
            "Add photo incentive — customers who include photos get a small reward.",
            "Showcase top reviews in social media and ads for social proof loop.",
            "Address every negative review publicly with a solution.",
        ],
        "catch_up": [
            "Launch a review campaign with post-purchase discount on next order.",
            "Use product inserts with a personal note from the founder.",
            "Partner with review-focused influencers in your niche.",
            "Run a limited giveaway with review request (compliant with platform TOS).",
        ],
        "compete": [
            "Focus on review quality — encourage photos and detailed feedback.",
            "Build a community of repeat buyers who review naturally.",
            "Leverage UGC from reviews in all marketing channels.",
            "Monitor competitor reviews weekly for emerging weaknesses.",
        ],
    }
    return all_tactics.get(phase, all_tactics["launch"])


def _estimate_timeline(our_count, comp_count):
    """Estimate months to close the review gap at different velocities."""
    gap = max(comp_count - our_count, 0)
    return {
        "conservative_months": round(gap / 10, 1) if gap > 0 else 0,
        "moderate_months": round(gap / 20, 1) if gap > 0 else 0,
        "aggressive_months": round(gap / 40, 1) if gap > 0 else 0,
        "review_gap": gap,
    }
