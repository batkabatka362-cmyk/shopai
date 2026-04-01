"""Differentiation domain knowledge — expert strategies and hard-won insights.

What veterans know about standing out from competitors:
  - "Best differentiation = solving a problem nobody else does"
  - "Brand story is hardest to copy"
  - "Features are easiest to copy"
  - "Service differentiation = highest ROI for small sellers"
  - "If you can't explain your difference in one sentence, it's not a difference"
"""
from __future__ import annotations

from typing import Any


# Core expert insights indexed by topic
DIFFERENTIATION_INSIGHTS = {
    "problem_solving": {
        "insight": "Best differentiation = solving a problem nobody else does",
        "explanation": (
            "The strongest market position comes from being the only one who "
            "solves a specific customer pain point. Customers will seek you out "
            "and pay a premium when you fix what nobody else fixes."
        ),
        "example": (
            "Every phone case protects. Only one brand made a case that doubles "
            "as a wallet, eliminating the need to carry both."
        ),
        "action": "Mine competitor reviews for unsolved complaints. Build your product around fixing one.",
    },
    "brand_story_moat": {
        "insight": "Brand story is the hardest thing to copy",
        "explanation": (
            "A competitor can copy your features in weeks, your pricing in days, "
            "and your content in hours. But they cannot copy your story — where "
            "you came from, why you started, and what you stand for."
        ),
        "example": (
            "Two sellers offer the same organic soap. One is a faceless brand. "
            "The other was started by a chemist with eczema who spent 3 years "
            "developing a gentle formula. Which do you trust?"
        ),
        "action": "Document your genuine origin story. Share it on every channel.",
    },
    "features_trap": {
        "insight": "Features are the easiest to copy — and the worst moat",
        "explanation": (
            "Adding features feels like differentiation, but any competitor with "
            "a decent supplier can match your features within one production cycle. "
            "Feature wars become a race to the bottom."
        ),
        "example": (
            "You add a built-in thermometer to your water bottle. Within 90 days, "
            "three competitors have the same feature at a lower price."
        ),
        "action": "Use features to get attention, but build moat elsewhere (brand, service, community).",
    },
    "service_roi": {
        "insight": "Service differentiation = highest ROI for small sellers",
        "explanation": (
            "Large sellers cannot provide personal, fast, caring service at scale. "
            "Small sellers can. Responding in 1 hour when competitors take 2 days "
            "creates loyal customers who leave great reviews and come back."
        ),
        "example": (
            "A small seller responds to every question within 30 minutes, includes "
            "handwritten thank-you notes, and follows up post-delivery. Their 4.9 "
            "rating makes them unbeatable despite higher prices."
        ),
        "action": "Set up alerts for customer messages. Respond within 1 hour during business hours.",
    },
    "simplicity_test": {
        "insight": "If you cannot explain your difference in one sentence, it is not a difference",
        "explanation": (
            "Customers scan listings in seconds. Your differentiation must be "
            "immediately obvious. Complex value propositions get ignored. "
            "Simple, clear statements get clicks."
        ),
        "example": (
            "Bad: 'Our product uses advanced polymer-infused nano-coating technology.' "
            "Good: 'The only cutting board that never needs oiling.'"
        ),
        "action": "Write your differentiator in 10 words or fewer. Test it with 5 people.",
    },
    "layered_moat": {
        "insight": "One differentiator is a tactic. Three differentiators is a moat.",
        "explanation": (
            "Any single advantage can be copied. But when you combine quality + "
            "brand story + exceptional service, competitors would need to replicate "
            "all three simultaneously — which almost never happens."
        ),
        "example": (
            "Premium leather goods + founder story from Italian craftsman family + "
            "lifetime repair guarantee. No single competitor matches all three."
        ),
        "action": "Build your primary differentiator first, then add layers over 6-12 months.",
    },
    "differentiation_vs_position": {
        "insight": "Differentiation is what you do. Positioning is what the customer thinks.",
        "explanation": (
            "You can have real differences that customers never notice. The gap "
            "between your actual differentiation and perceived differentiation is "
            "where marketing dollars should go."
        ),
        "example": (
            "Your product is objectively better quality, but your photos look cheap. "
            "Customers perceive you as budget. Fix the photos, not the product."
        ),
        "action": "Audit how customers perceive you vs reality. Close perception gaps first.",
    },
}


# Detailed playbooks for each strategy type
DIFFERENTIATION_PLAYBOOKS = {
    "better_quality": {
        "week_1": "Audit competitor quality — order top 3 products, document weaknesses",
        "week_2_3": "Source improved materials, negotiate with 2-3 suppliers",
        "week_4_6": "Produce samples, run quality tests, photograph results",
        "week_7_8": "Update listing with quality proof — certifications, comparison photos",
        "ongoing": "Monitor reviews for quality mentions, iterate on feedback",
        "kpi": "Average review rating 0.3+ points above nearest competitor",
    },
    "better_service": {
        "week_1": "Set up rapid response system (alerts, templates, tracking)",
        "week_2": "Create FAQ page and common resolution playbook",
        "week_3_4": "Launch post-purchase follow-up sequence",
        "week_5_6": "Add personalized touches (notes, samples, tips)",
        "ongoing": "Measure response time, resolution rate, repeat purchase rate",
        "kpi": "Response time under 2 hours, satisfaction rate above 95%",
    },
    "niche_focus": {
        "week_1": "Research sub-segments — who is underserved in this category?",
        "week_2_3": "Validate niche demand — search volume, forum activity, social mentions",
        "week_4_6": "Adapt product and messaging for the specific niche audience",
        "week_7_8": "Create niche-specific content and community presence",
        "ongoing": "Deepen expertise, engage with niche community, expand product line",
        "kpi": "Top 3 ranking for niche-specific keywords within 90 days",
    },
    "brand_story": {
        "week_1": "Document your genuine story — why you started, what drives you",
        "week_2_3": "Develop visual brand identity — logo, colors, photography style",
        "week_4_6": "Create brand content — about page, social profiles, video",
        "week_7_8": "Integrate brand story into product listings and packaging",
        "ongoing": "Share ongoing story updates — new products, behind-the-scenes, milestones",
        "kpi": "Brand search volume increase of 20% within 6 months",
    },
    "bundling": {
        "week_1": "Analyze purchase patterns — what do customers buy together?",
        "week_2": "Design 2-3 bundle concepts with clear savings messaging",
        "week_3_4": "Source bundle components, calculate margins, create packaging",
        "week_5_6": "Launch bundles, run A/B tests on pricing and composition",
        "ongoing": "Rotate bundles seasonally, test new combinations quarterly",
        "kpi": "Average order value increase of 25% from bundle sales",
    },
    "customization": {
        "week_1": "Survey customers — what would they customize if they could?",
        "week_2_3": "Design customization workflow (options, preview, production)",
        "week_4_6": "Set up production process for custom orders",
        "week_7_8": "Launch with limited options, collect feedback, iterate",
        "ongoing": "Expand customization options based on demand data",
        "kpi": "Custom orders at 30%+ margin premium over standard products",
    },
}


def get_insight(topic: str) -> dict[str, Any]:
    """Get expert insight on a differentiation topic."""
    return DIFFERENTIATION_INSIGHTS.get(topic, {
        "insight": "No specific insight available for this topic",
        "explanation": "Consult the general differentiation framework",
        "example": "",
        "action": "Research competitors and identify gaps",
    })


def get_playbook(strategy_type: str) -> dict[str, Any]:
    """Get week-by-week playbook for implementing a differentiation strategy."""
    return DIFFERENTIATION_PLAYBOOKS.get(strategy_type, {
        "week_1": "Research and define custom strategy",
        "week_2_3": "Plan implementation approach",
        "week_4_6": "Execute initial implementation",
        "ongoing": "Monitor results and iterate",
        "kpi": "Define custom KPI for this strategy",
    })
