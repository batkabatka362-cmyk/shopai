"""Content Generation Engine — copy writer.

Writes the actual marketing copy: headlines, body text, bullet points, and
calls-to-action, tailored to the content type and tone.

Model note: Uses LLaMA for creative writing tasks.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Content-type templates and constraints
# ---------------------------------------------------------------------------

_CONTENT_TEMPLATES: dict[str, dict[str, Any]] = {
    "product_description": {
        "headline_pattern": "{benefit} — {product}",
        "body_length": (150, 300),
        "bullet_count": (3, 6),
        "cta_style": "purchase",
    },
    "ad_copy": {
        "headline_pattern": "{hook} {product}",
        "body_length": (25, 90),
        "bullet_count": (0, 3),
        "cta_style": "click",
    },
    "social_post": {
        "headline_pattern": "{hook}",
        "body_length": (50, 150),
        "bullet_count": (0, 3),
        "cta_style": "engage",
    },
    "blog": {
        "headline_pattern": "{topic}: {angle}",
        "body_length": (800, 1500),
        "bullet_count": (3, 8),
        "cta_style": "learn_more",
    },
    "email": {
        "headline_pattern": "{personalized_hook}",
        "body_length": (100, 300),
        "bullet_count": (2, 5),
        "cta_style": "conversion",
    },
}

_CTA_PHRASES: dict[str, list[str]] = {
    "purchase": [
        "Shop Now",
        "Add to Cart",
        "Get Yours Today",
        "Buy Now and Save",
    ],
    "click": [
        "Learn More",
        "See the Deal",
        "Tap to Discover",
        "Don't Miss Out",
    ],
    "engage": [
        "Tell us what you think!",
        "Tag a friend who needs this",
        "Double-tap if you agree",
        "Share your experience",
    ],
    "learn_more": [
        "Read the Full Guide",
        "Discover More Tips",
        "Continue Reading",
        "Explore Our Resources",
    ],
    "conversion": [
        "Claim Your Offer",
        "Get Started Today",
        "Unlock Your Discount",
        "Take the Next Step",
    ],
}

_TONE_ADJECTIVES: dict[str, list[str]] = {
    "professional": ["reliable", "trusted", "proven", "industry-leading"],
    "casual": ["awesome", "cool", "handy", "go-to"],
    "urgent": ["limited-time", "exclusive", "last-chance", "hurry"],
    "luxury": ["exquisite", "premium", "refined", "distinguished"],
    "playful": ["fun", "exciting", "delightful", "surprising"],
    "informative": ["comprehensive", "essential", "detailed", "thorough"],
}


def write_copy(
    brief_analysis: dict[str, Any],
    tone_selection: dict[str, Any],
    keyword_extraction: dict[str, Any],
    product: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Write marketing copy based on analysis results.

    Args:
        brief_analysis: Output from brief_analyzer.
        tone_selection: Output from tone_selector.
        keyword_extraction: Output from keyword_extractor.
        product: Original ProductData dict.
        brand: Original BrandData dict.

    Returns:
        Structured dict with CopyDraft data.
    """
    try:
        prod = copy.deepcopy(product)
        brnd = copy.deepcopy(brand)

        title = str(prod.get("title", "Product")).strip()
        features = list(prod.get("features", []))
        price = prod.get("price", 0.0)
        category = str(prod.get("category", "")).strip()

        brand_name = str(brnd.get("name", "")).strip()

        content_type = str(brief_analysis.get("content_type", "product_description"))
        usps = list(brief_analysis.get("usps", features[:3]))
        target_audience = str(brief_analysis.get("target_audience", "consumers"))
        desired_outcome = str(brief_analysis.get("desired_outcome", ""))

        primary_tone = str(tone_selection.get("primary_tone", "professional"))
        emotional_appeal = str(tone_selection.get("emotional_appeal", "trust"))

        primary_keywords = list(keyword_extraction.get("primary_keywords", []))
        secondary_keywords = list(keyword_extraction.get("secondary_keywords", []))

        template = _CONTENT_TEMPLATES.get(
            content_type, _CONTENT_TEMPLATES["product_description"],
        )

        # --- Build headline ---
        headline = _build_headline(
            title, usps, primary_tone, category, content_type,
        )
        alt_headlines = _build_alt_headlines(
            title, usps, primary_tone, category,
        )

        # --- Build body ---
        body = _build_body(
            title, features, usps, primary_tone, emotional_appeal,
            target_audience, primary_keywords, secondary_keywords,
            brand_name, price, content_type, template,
        )

        # --- Build bullets ---
        bullets = _build_bullets(features, usps, primary_tone, template)

        # --- Select CTA ---
        cta_style = template.get("cta_style", "purchase")
        cta_options = _CTA_PHRASES.get(cta_style, _CTA_PHRASES["purchase"])
        cta = cta_options[0]

        return {
            "status": "success",
            "draft": {
                "headline": headline,
                "body": body,
                "bullets": bullets,
                "cta": cta,
                "alt_headlines": alt_headlines,
                "model_note": "LLaMA: creative copy generation with tone and keyword integration",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "draft": {},
            "error": f"Copy writing failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Headline builders
# ---------------------------------------------------------------------------

def _build_headline(
    title: str,
    usps: list[str],
    tone: str,
    category: str,
    content_type: str,
) -> str:
    """Build the primary headline."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    adj = adjectives[0] if adjectives else "quality"

    usp_text = usps[0] if usps else "quality"

    if content_type == "ad_copy":
        return f"Discover the {adj.title()} {title}"
    elif content_type == "social_post":
        return f"{usp_text.capitalize()} — Meet the {title}"
    elif content_type == "blog":
        return f"Why {title} Is the {adj.title()} Choice for {category.title() or 'You'}"
    elif content_type == "email":
        return f"Your {adj.title()} {category.title() or 'Product'} Awaits"
    else:
        # product_description default
        return f"{title} — {adj.title()} {category.title() or 'Product'} for Every Need"


def _build_alt_headlines(
    title: str,
    usps: list[str],
    tone: str,
    category: str,
) -> list[str]:
    """Build alternative headline variations."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    alts: list[str] = []

    if len(adjectives) > 1:
        alts.append(f"The {adjectives[1].title()} {title} You've Been Looking For")
    if usps:
        alts.append(f"{usps[0].capitalize()} — Introducing {title}")
    if category:
        alts.append(f"Elevate Your {category.title()} Experience with {title}")

    return alts[:3]


# ---------------------------------------------------------------------------
# Body builder
# ---------------------------------------------------------------------------

def _build_body(
    title: str,
    features: list[str],
    usps: list[str],
    tone: str,
    emotional_appeal: str,
    audience: str,
    primary_kw: list[str],
    secondary_kw: list[str],
    brand_name: str,
    price: float,
    content_type: str,
    template: dict[str, Any],
) -> str:
    """Build the body text with keyword integration."""
    adjectives = _TONE_ADJECTIVES.get(tone, _TONE_ADJECTIVES["professional"])
    adj = adjectives[0] if adjectives else "quality"

    brand_mention = f"by {brand_name} " if brand_name else ""

    # Opening sentence
    opening = (
        f"Introducing the {title} {brand_mention}— a {adj} solution designed "
        f"for {audience}."
    )

    # Feature sentences
    feature_sentences: list[str] = []
    for i, feat in enumerate(features[:4]):
        kw_insert = ""
        if i < len(primary_kw):
            kw_insert = f" As a top {primary_kw[i]},"
        feature_sentences.append(
            f"{kw_insert} {feat.strip().rstrip('.')}." if kw_insert
            else f"{feat.strip().rstrip('.')}."
        )

    # USP paragraph
    usp_parts = [u.strip().rstrip(".") for u in usps[:3]]
    usp_sentence = ""
    if usp_parts:
        usp_sentence = (
            f"What sets this apart: {', '.join(usp_parts)}."
        )

    # Closing
    if price and price > 0:
        closing = (
            f"Available at ${price:.2f}, the {title} delivers outstanding value."
        )
    else:
        closing = f"The {title} is ready to exceed your expectations."

    # Secondary keyword weaving
    kw_sentence = ""
    if secondary_kw:
        kw_terms = ", ".join(secondary_kw[:3])
        kw_sentence = f"Key highlights include {kw_terms}."

    # Assemble based on content type length
    parts = [opening]
    parts.extend(feature_sentences)
    if usp_sentence:
        parts.append(usp_sentence)
    if kw_sentence:
        parts.append(kw_sentence)
    parts.append(closing)

    body = " ".join(parts)

    # Trim for short-form content
    min_len, max_len = template.get("body_length", (150, 300))
    if content_type in ("ad_copy", "social_post"):
        # Keep it short: opening + closing
        body = f"{opening} {usp_sentence} {closing}".strip()
        words = body.split()
        if len(words) > max_len:
            body = " ".join(words[:max_len])

    return body


# ---------------------------------------------------------------------------
# Bullet builder
# ---------------------------------------------------------------------------

def _build_bullets(
    features: list[str],
    usps: list[str],
    tone: str,
    template: dict[str, Any],
) -> list[str]:
    """Build bullet point list from features and USPs."""
    min_count, max_count = template.get("bullet_count", (3, 6))

    bullets: list[str] = []
    for feat in features:
        clean = feat.strip().rstrip(".")
        if clean:
            bullets.append(clean)

    # Fill with USPs if needed
    existing = {b.lower() for b in bullets}
    for usp in usps:
        clean = usp.strip().rstrip(".")
        if clean and clean.lower() not in existing:
            bullets.append(clean)
            existing.add(clean.lower())

    return bullets[:max_count]
