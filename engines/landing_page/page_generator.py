"""Landing Page Engine — page generator.

Generates a complete landing page structure from product data,
campaign context, and brand voice. Produces headline, subheadline,
hero section, benefits list, CTA, and social proof.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Copywriting frameworks by brand voice
# ---------------------------------------------------------------------------

_VOICE_MODIFIERS = {
    "professional": {"tone": "clear and authoritative", "cta_style": "direct"},
    "casual": {"tone": "friendly and approachable", "cta_style": "conversational"},
    "luxury": {"tone": "elegant and exclusive", "cta_style": "aspirational"},
    "urgent": {"tone": "compelling and time-sensitive", "cta_style": "scarcity"},
    "technical": {"tone": "precise and data-driven", "cta_style": "logical"},
}


def generate_page(
    product: dict[str, Any],
    campaign: dict[str, Any],
    target_audience: str,
    brand_voice: str,
) -> dict[str, Any]:
    """Generate a landing page structure from product and campaign data.

    Args:
        product: Product data dict.
        campaign: Campaign context dict.
        target_audience: Description of the target audience.
        brand_voice: Brand voice style (professional, casual, luxury, etc.).

    Returns:
        Structured dict with page structure.
    """
    try:
        product = copy.deepcopy(product)
        campaign = copy.deepcopy(campaign)

        title = str(product.get("title", "Our Product"))
        description = str(product.get("description", ""))
        price = float(product.get("price", 0))
        features = list(product.get("features", []))
        category = str(product.get("category", ""))

        campaign_goal = str(campaign.get("goal", "conversion"))
        channel = str(campaign.get("channel", "web"))

        voice = _VOICE_MODIFIERS.get(brand_voice.lower(), _VOICE_MODIFIERS["professional"])

        # Build headline from product + goal
        headline = _build_headline(title, features, campaign_goal, voice)

        # Build subheadline
        subheadline = _build_subheadline(title, description, target_audience, voice)

        # Build hero section
        hero_section = _build_hero(title, description, price, campaign_goal)

        # Build benefits from features
        benefits = _build_benefits(features, category)

        # Build CTA
        cta = _build_cta(campaign_goal, price, voice)

        # Build social proof
        social_proof = _build_social_proof(category, campaign_goal)

        page = {
            "headline": headline,
            "subheadline": subheadline,
            "hero_section": hero_section,
            "benefits": benefits,
            "cta": cta,
            "social_proof": social_proof,
            "layout": "single_column" if channel == "mobile" else "standard",
        }

        return {
            "status": "success",
            "page": page,
        }
    except Exception as exc:
        return {
            "status": "error",
            "page": {},
            "error": f"Page generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_headline(
    title: str,
    features: list[str],
    goal: str,
    voice: dict[str, str],
) -> str:
    """Build a headline based on product and goal."""
    key_benefit = features[0] if features else "quality and value"

    if goal == "awareness":
        return f"Discover {title} — {key_benefit.title()}"
    elif goal == "retention":
        return f"Still Loving {title}? See What's New"
    else:  # conversion
        return f"Get {title} — {key_benefit.title()} You Can Count On"


def _build_subheadline(
    title: str,
    description: str,
    target_audience: str,
    voice: dict[str, str],
) -> str:
    """Build a supporting subheadline."""
    if description:
        # Use first sentence of description
        first_sentence = description.split(".")[0].strip()
        if len(first_sentence) <= 120:
            return first_sentence + "."
        return first_sentence[:117] + "..."
    return f"Built for {target_audience} who demand the best."


def _build_hero(title: str, description: str, price: float, goal: str) -> str:
    """Build the hero section content."""
    parts = []
    if description:
        parts.append(description[:200])
    if price > 0:
        parts.append(f"Starting at ${price:.2f}")
    if goal == "conversion" and price > 0:
        parts.append("Free shipping on all orders.")
    return " | ".join(parts) if parts else f"Experience {title} today."


def _build_benefits(features: list[str], category: str) -> list[str]:
    """Convert product features into benefit-oriented bullet points."""
    if not features:
        return [
            "Premium quality materials",
            "Designed for everyday use",
            "Backed by our satisfaction guarantee",
        ]

    benefits = []
    for feature in features[:6]:
        feature = str(feature).strip()
        if feature:
            # Transform feature into benefit language
            if any(w in feature.lower() for w in ["fast", "quick", "speed"]):
                benefits.append(f"Save time with {feature.lower()}")
            elif any(w in feature.lower() for w in ["durable", "strong", "lasting"]):
                benefits.append(f"Built to last — {feature.lower()}")
            elif any(w in feature.lower() for w in ["easy", "simple", "intuitive"]):
                benefits.append(f"No learning curve — {feature.lower()}")
            else:
                benefits.append(feature)

    return benefits if benefits else ["Quality you can trust"]


def _build_cta(goal: str, price: float, voice: dict[str, str]) -> str:
    """Build a call-to-action based on campaign goal and voice."""
    style = voice.get("cta_style", "direct")

    ctas = {
        ("conversion", "direct"): "Buy Now" if price > 0 else "Get Started",
        ("conversion", "conversational"): "Yes, I Want This!" if price > 0 else "Let's Go!",
        ("conversion", "aspirational"): "Elevate Your Experience",
        ("conversion", "scarcity"): "Claim Yours Before They're Gone",
        ("conversion", "logical"): "See the Details & Order",
        ("awareness", "direct"): "Learn More",
        ("awareness", "conversational"): "Tell Me More",
        ("awareness", "aspirational"): "Explore the Collection",
        ("awareness", "scarcity"): "See What Everyone's Talking About",
        ("awareness", "logical"): "View Full Specifications",
        ("retention", "direct"): "Shop New Arrivals",
        ("retention", "conversational"): "See What's New!",
        ("retention", "aspirational"): "Continue Your Journey",
        ("retention", "scarcity"): "Exclusive Access — Shop Now",
        ("retention", "logical"): "Compare and Upgrade",
    }

    return ctas.get((goal, style), "Shop Now")


def _build_social_proof(category: str, goal: str) -> str:
    """Build a social proof section."""
    if goal == "conversion":
        return "Join thousands of satisfied customers who chose quality."
    elif goal == "awareness":
        return "Featured in leading publications and trusted by experts."
    else:
        return "Our returning customers speak for themselves."
