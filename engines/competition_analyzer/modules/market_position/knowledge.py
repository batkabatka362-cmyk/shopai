"""Market position domain knowledge — expert strategies for positioning.

What veterans know about market positioning:
  - "Position in the mind, not just the market"
  - "Premium position requires premium everything (packaging, photos, service)"
  - "Niche specialist beats generalist in small markets"
  - "Your position is not what you say — it's what customers believe"
  - "Repositioning is 10x harder than positioning correctly the first time"
"""
from __future__ import annotations

from typing import Any


# Core expert insights indexed by topic
POSITIONING_INSIGHTS = {
    "position_in_mind": {
        "insight": "Position in the mind, not just the market",
        "explanation": (
            "Your market position exists in the customer's perception, not in "
            "your spreadsheet. You can be objectively premium but perceived as "
            "budget if your photos, packaging, and messaging look cheap. "
            "Positioning is a perception game."
        ),
        "example": (
            "Two identical products. One has professional lifestyle photos, "
            "clean white packaging, and a brand story. The other has factory "
            "photos and a generic listing. Customers perceive the first as "
            "premium and willingly pay 40% more."
        ),
        "action": (
            "Audit every customer touchpoint. Does it match your intended "
            "position? Fix perception gaps before changing the actual product."
        ),
    },
    "premium_requires_everything": {
        "insight": "Premium position requires premium everything",
        "explanation": (
            "Customers assess premium through every detail: packaging, "
            "photography, listing copy, response time, shipping speed, and "
            "return policy. One cheap element ruins the entire premium perception. "
            "Premium is a system, not a price tag."
        ),
        "example": (
            "A seller prices at premium but ships in a plain brown box with "
            "a packing slip. The unboxing experience destroys the premium "
            "perception. Customer leaves a 3-star review: 'Product is fine but "
            "feels overpriced.' Premium lost."
        ),
        "action": (
            "List every customer touchpoint. Rate each 1-5 for premium feel. "
            "Anything below 4 must be upgraded before claiming premium position."
        ),
    },
    "niche_beats_generalist": {
        "insight": "Niche specialist beats generalist in small markets",
        "explanation": (
            "In a market with fewer than 50 serious competitors, the specialist "
            "who deeply understands one sub-segment will outperform the generalist "
            "who serves everyone. Specialists command higher prices, earn more "
            "trust, and build stronger repeat purchase behavior."
        ),
        "example": (
            "A generalist sells yoga mats for everyone. A specialist sells yoga "
            "mats specifically for hot yoga practitioners with extra grip and "
            "antimicrobial coating. The specialist gets all the hot yoga customers "
            "and charges 2x the price."
        ),
        "action": (
            "Identify the most passionate sub-segment in your category. "
            "Tailor everything — product, content, messaging — for them specifically."
        ),
    },
    "customer_belief": {
        "insight": "Your position is what customers believe, not what you claim",
        "explanation": (
            "Claiming 'premium quality' in your listing means nothing if "
            "reviews say otherwise. Position is earned through consistent "
            "experience, not declared through marketing copy. Let customers "
            "define your position through their words."
        ),
        "example": (
            "A seller declares 'luxury bedsheets' but reviews say 'good for "
            "the price.' The actual position is value, not luxury. Fighting "
            "this perception wastes money. Embrace the value position instead."
        ),
        "action": (
            "Read your reviews. What words do customers use to describe you? "
            "That is your real position. Align strategy with reality."
        ),
    },
    "repositioning_cost": {
        "insight": "Repositioning is 10x harder than positioning correctly the first time",
        "explanation": (
            "Once customers and the algorithm categorize you, changing that "
            "perception requires sustained effort over months. Existing reviews "
            "anchor your old position. New customers see old reviews first. "
            "It is far better to choose the right position from day one."
        ),
        "example": (
            "A budget seller tries to go premium. Existing 1000 reviews say "
            "'great value for money.' New premium customers see those reviews "
            "and think 'not actually premium.' The old reviews become an anchor "
            "that takes 6-12 months of new reviews to dilute."
        ),
        "action": (
            "If repositioning is necessary, consider launching under a new brand "
            "or product line rather than trying to shift an existing one."
        ),
    },
    "empty_position_trap": {
        "insight": "An empty position might be empty for a reason",
        "explanation": (
            "Finding no competitors in a position is exciting, but investigate "
            "why it is empty before rushing in. Maybe nobody can make margins "
            "there. Maybe customer demand does not exist at that tier. Maybe "
            "others tried and failed."
        ),
        "example": (
            "No premium option exists in a commodity category. A seller "
            "launches a premium version. Nobody buys it because customers "
            "in this category only care about price. The gap was real but "
            "unprofitable."
        ),
        "action": (
            "Before filling an empty position, validate demand. Check if "
            "customers in this category have ever asked for what you plan to offer."
        ),
    },
    "consistency_wins": {
        "insight": "Consistent positioning beats perfect positioning",
        "explanation": (
            "A seller who consistently delivers on a value position will "
            "outperform a seller who inconsistently tries to be premium. "
            "Customers value predictability. Every interaction should reinforce "
            "the same message about who you are."
        ),
        "example": (
            "A value-positioned seller ships every order in 2 days, responds "
            "within 4 hours, and maintains 4.5 stars for 3 years. Customers "
            "trust them completely. A premium competitor with inconsistent "
            "service and 4.0 stars loses to the reliable value player."
        ),
        "action": (
            "Pick a position you can sustain every single day. Consistency "
            "over 12 months beats perfection for 1 month."
        ),
    },
}


# Step-by-step playbooks for executing each positioning strategy
POSITIONING_PLAYBOOKS = {
    "budget_leader": {
        "week_1_2": "Analyze cost structure — identify every cost reduction opportunity",
        "week_3_4": "Negotiate with suppliers for volume discounts or alternate sourcing",
        "week_5_6": "Optimize listing for price-focused keywords ('affordable', 'best deal')",
        "week_7_8": "Set up automated repricing to maintain lowest-price position",
        "ongoing": "Monitor competitor prices daily, continuously reduce costs",
        "kpi": "Maintain lowest price while keeping margin above 15%",
        "warning": "Budget position is hardest to defend — always someone willing to go lower",
    },
    "value_leader": {
        "week_1_2": "Benchmark quality against top 5 competitors — find the sweet spot",
        "week_3_4": "Optimize product to maximize perceived quality at moderate cost",
        "week_5_6": "Create comparison content showing value vs premium and budget options",
        "week_7_8": "Launch review-collection campaign emphasizing quality-for-price",
        "ongoing": "Monitor quality consistency, collect reviews, adjust price as needed",
        "kpi": "4.3+ average rating with price at 60th percentile or below",
        "warning": "Value position requires constant quality monitoring — one bad batch hurts",
    },
    "premium": {
        "week_1_2": "Audit all touchpoints for premium consistency (photos, packaging, copy)",
        "week_3_4": "Invest in professional photography and premium packaging design",
        "week_5_6": "Upgrade service level — faster response, better returns policy",
        "week_7_8": "Launch with premium pricing and brand-forward listing content",
        "ongoing": "Maintain premium standards, collect photo reviews, build brand presence",
        "kpi": "4.5+ rating, price at 75th+ percentile, premium mentioned in reviews",
        "warning": "One subpar experience ruins premium perception — quality control is critical",
    },
    "ultra_premium": {
        "week_1_2": "Define the luxury story — what makes this genuinely exclusive?",
        "week_3_4": "Source or create truly exceptional product with verifiable quality",
        "week_5_6": "Design luxury packaging, unboxing experience, and premium inserts",
        "week_7_8": "Launch with aspirational content, lifestyle imagery, limited availability",
        "ongoing": "Cultivate brand community, maintain scarcity, deliver exceptional service",
        "kpi": "4.7+ rating, top 10% price, strong brand search volume",
        "warning": "Ultra-premium only works with authentic quality — never fake luxury",
    },
    "niche_specialist": {
        "week_1_2": "Define exact niche audience — demographics, needs, language, communities",
        "week_3_4": "Adapt product features specifically for the niche use case",
        "week_5_6": "Create niche-specific content using the audience's own language",
        "week_7_8": "Engage with niche communities — forums, groups, influencers",
        "ongoing": "Deepen expertise, expand niche product line, build authority",
        "kpi": "Top 3 ranking for niche keywords, recognized expert in community",
        "warning": "Ensure niche is large enough for sustainable revenue before committing",
    },
}


def get_insight(topic: str) -> dict[str, Any]:
    """Get expert insight on a market positioning topic."""
    return POSITIONING_INSIGHTS.get(topic, {
        "insight": "No specific insight available for this topic",
        "explanation": "Consult the general positioning framework",
        "example": "",
        "action": "Research your market position relative to competitors",
    })


def get_playbook(position: str) -> dict[str, Any]:
    """Get step-by-step playbook for executing a specific positioning strategy."""
    return POSITIONING_PLAYBOOKS.get(position, {
        "week_1_2": "Research and define your positioning strategy",
        "week_3_4": "Align product and content with chosen position",
        "week_5_6": "Launch with consistent positioning across all touchpoints",
        "ongoing": "Monitor customer perception and adjust as needed",
        "kpi": "Define custom KPI for your positioning approach",
        "warning": "Custom positioning requires careful ongoing management",
    })
