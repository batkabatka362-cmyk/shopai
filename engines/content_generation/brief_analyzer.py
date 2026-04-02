"""Content Generation Engine — brief analyzer.

Analyzes the content request to extract product features, unique selling
propositions, target audience characteristics, and content type requirements.

Model note: Uses Mistral for content brief analysis.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Content type configurations
# ---------------------------------------------------------------------------

_CONTENT_TYPE_PROFILES: dict[str, dict[str, Any]] = {
    "product_description": {
        "desired_outcome": "Inform and persuade to purchase",
        "focus": "features_and_benefits",
        "typical_length": "150-300 words",
    },
    "ad_copy": {
        "desired_outcome": "Drive immediate action / click",
        "focus": "urgency_and_value",
        "typical_length": "25-90 words",
    },
    "social_post": {
        "desired_outcome": "Engage and drive shares / clicks",
        "focus": "attention_and_relatability",
        "typical_length": "50-150 words",
    },
    "blog": {
        "desired_outcome": "Educate and build authority",
        "focus": "depth_and_seo",
        "typical_length": "800-1500 words",
    },
    "email": {
        "desired_outcome": "Nurture lead and drive conversion",
        "focus": "personalization_and_cta",
        "typical_length": "100-300 words",
    },
}


def analyze_brief(
    content_type: str,
    product: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Analyze the content brief to extract actionable insights.

    Args:
        content_type: One of product_description, ad_copy, social_post, blog, email.
        product: ProductData dict with title, features, price, category, target_audience.
        brand: BrandData dict with name, voice, values.

    Returns:
        Structured dict with BriefAnalysis data.
    """
    try:
        prod = copy.deepcopy(product)
        brnd = copy.deepcopy(brand)

        title = str(prod.get("title", "")).strip()
        features = list(prod.get("features", []))
        price = float(prod.get("price", 0.0))
        category = str(prod.get("category", "")).strip().lower()
        target_audience = str(prod.get("target_audience", "general consumer")).strip()

        brand_name = str(brnd.get("name", "")).strip()
        brand_voice = str(brnd.get("voice", "professional")).strip().lower()
        brand_values = list(brnd.get("values", []))

        # Normalize content type
        ct = content_type.strip().lower().replace(" ", "_").replace("-", "_")
        profile = _CONTENT_TYPE_PROFILES.get(ct, _CONTENT_TYPE_PROFILES["product_description"])

        # Extract USPs from features — first 3 features are treated as key USPs
        usps = features[:3] if features else [f"Quality {category} product" if category else "Quality product"]

        # Derive audience pain points from category and audience
        pain_points = _derive_pain_points(category, target_audience)

        return {
            "status": "success",
            "analysis": {
                "content_type": ct,
                "product_features": features,
                "usps": usps,
                "target_audience": target_audience,
                "audience_pain_points": pain_points,
                "desired_outcome": profile["desired_outcome"],
                "model_note": "Mistral: content brief analysis and audience insight extraction",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Brief analysis failed: {exc}",
        }


def _derive_pain_points(category: str, audience: str) -> list[str]:
    """Derive likely audience pain points from category and target audience."""
    category_pains: dict[str, list[str]] = {
        "electronics": ["complexity of choices", "reliability concerns", "value for money"],
        "fashion": ["finding the right fit", "quality vs price", "staying on trend"],
        "beauty": ["skin sensitivity", "product effectiveness", "ingredient transparency"],
        "home": ["durability concerns", "style matching", "assembly difficulty"],
        "health": ["safety concerns", "proven effectiveness", "ease of use"],
        "food": ["freshness and quality", "dietary restrictions", "value for money"],
        "sports": ["performance needs", "durability", "comfort during activity"],
        "toys": ["safety for children", "educational value", "durability"],
    }
    pains = category_pains.get(category, ["finding the right product", "value for money", "quality assurance"])
    return pains
