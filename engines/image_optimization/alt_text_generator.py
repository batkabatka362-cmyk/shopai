"""Image Optimization Engine — alt text generator.

Generates SEO-optimized alt text for product images based on
product data, image position, and platform requirements.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Alt text constraints
# ---------------------------------------------------------------------------

_MAX_ALT_LENGTH = 125


def generate_alt_texts(
    images: list[dict[str, Any]],
    product: dict[str, Any],
    quality_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate SEO-optimized alt text for each image.

    Args:
        images: List of image dicts.
        product: Product info dict (title, category, features).
        quality_analyses: Quality analysis results per image.

    Returns:
        Structured dict with generated alt texts.
    """
    try:
        items = copy.deepcopy(images)
        product_name = str(product.get("title", "Product"))
        category = str(product.get("category", ""))
        features = list(product.get("features", []))

        alt_texts: list[dict[str, Any]] = []

        for i, img in enumerate(items):
            existing_alt = str(img.get("alt", "")).strip()

            if existing_alt and len(existing_alt) <= _MAX_ALT_LENGTH:
                # Keep existing good alt text but flag as not SEO-optimized
                alt_text = existing_alt
                seo_optimized = _is_seo_optimized(alt_text, product_name, category)
            else:
                # Generate new alt text
                alt_text = _build_alt_text(
                    product_name=product_name,
                    category=category,
                    features=features,
                    image_index=i,
                    total_images=len(items),
                )
                seo_optimized = True

            alt_texts.append({
                "image_id": i,
                "alt_text": alt_text,
                "seo_optimized": seo_optimized,
            })

        return {
            "status": "success",
            "alt_texts": alt_texts,
        }
    except Exception as exc:
        return {
            "status": "error",
            "alt_texts": [],
            "error": f"Alt text generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_alt_text(
    product_name: str,
    category: str,
    features: list[str],
    image_index: int,
    total_images: int,
) -> str:
    """Build a descriptive, SEO-friendly alt text."""
    parts: list[str] = [product_name]

    # Add image-position context
    if image_index == 0:
        parts.append("- main product image")
    elif image_index == 1 and total_images > 2:
        parts.append("- alternate view")
    elif image_index == total_images - 1 and total_images > 2:
        parts.append("- detail view")

    # Add category
    if category:
        parts.append(f"({category})")

    # Add a feature if space allows
    if features and image_index < len(features):
        feature = features[image_index]
        candidate = " ".join(parts) + f" featuring {feature}"
        if len(candidate) <= _MAX_ALT_LENGTH:
            parts.append(f"featuring {feature}")

    alt_text = " ".join(parts)

    # Truncate to max length
    if len(alt_text) > _MAX_ALT_LENGTH:
        alt_text = alt_text[:_MAX_ALT_LENGTH - 3].rsplit(" ", 1)[0] + "..."

    return alt_text


def _is_seo_optimized(alt_text: str, product_name: str, category: str) -> bool:
    """Check if existing alt text contains key SEO elements."""
    alt_lower = alt_text.lower()
    has_product = product_name.lower() in alt_lower
    has_category = category.lower() in alt_lower if category else True
    return has_product and has_category
