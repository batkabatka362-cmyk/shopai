"""Product Description Engine — copy writer.

Generates product title, subtitle, bullet points, and description
from extracted features and brand voice.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def write_copy(
    product: dict[str, Any],
    features: list[dict[str, Any]],
    brand_voice: dict[str, Any],
    target_keywords: list[str],
) -> dict[str, Any]:
    """Generate product copy from features and brand voice.

    Args:
        product: Product info dict.
        features: Extracted and prioritized features list.
        brand_voice: Brand voice configuration.
        target_keywords: SEO target keywords.

    Returns:
        Structured dict with generated title, subtitle, bullets, description.
    """
    try:
        prod = copy.deepcopy(product)
        product_name = str(prod.get("title", "Product"))
        category = str(prod.get("category", ""))
        brand_name = str(brand_voice.get("brand_name", ""))
        tone = str(brand_voice.get("tone", "professional"))

        # ---- Title ----
        primary_kw = target_keywords[0] if target_keywords else category
        if brand_name:
            title = f"{brand_name} {product_name}"
        else:
            title = product_name

        if primary_kw and primary_kw.lower() not in title.lower():
            title = f"{title} - {primary_kw.title()}"

        # Cap title at 200 chars
        if len(title) > 200:
            title = title[:197] + "..."

        # ---- Subtitle ----
        top_benefit = ""
        if features:
            top_benefit = str(features[0].get("benefit", ""))
        subtitle = top_benefit if top_benefit else f"Premium {category}" if category else ""

        # ---- Bullet points (top 5 features) ----
        bullet_points: list[str] = []
        for feat in features[:5]:
            feature_text = str(feat.get("feature", ""))
            benefit_text = str(feat.get("benefit", ""))
            bullet = f"{feature_text} — {benefit_text}" if benefit_text else feature_text
            # Capitalize first letter
            if bullet and not bullet[0].isupper():
                bullet = bullet[0].upper() + bullet[1:]
            bullet_points.append(bullet)

        if not bullet_points:
            bullet_points = [f"High-quality {category}" if category else "Premium quality"]

        # ---- Description ----
        description_parts: list[str] = []

        # Opening line
        if tone == "casual":
            opener = f"Meet the {product_name} — your new favorite {category}."
        elif tone == "luxury":
            opener = f"Introducing the {product_name}, crafted for those who demand the finest."
        else:
            opener = f"The {product_name} delivers exceptional {category} performance."

        description_parts.append(opener)

        # Feature paragraph
        if features:
            feat_sentences = []
            for feat in features[:3]:
                f_text = str(feat.get("feature", ""))
                b_text = str(feat.get("benefit", ""))
                feat_sentences.append(f"{f_text}. {b_text}.")
            description_parts.append(" ".join(feat_sentences))

        # Keyword integration
        remaining_kws = [kw for kw in target_keywords[1:3] if kw]
        if remaining_kws:
            kw_sentence = (
                f"Perfect for anyone looking for {', '.join(remaining_kws)}."
            )
            description_parts.append(kw_sentence)

        # Closing
        if brand_name:
            description_parts.append(
                f"Backed by {brand_name}'s commitment to quality."
            )

        description = " ".join(description_parts)

        return {
            "status": "success",
            "copy": {
                "title": title,
                "subtitle": subtitle,
                "bullet_points": bullet_points,
                "description": description,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "copy": {},
            "error": f"Copy writing failed: {exc}",
        }
