"""Content Generation Engine — keyword extractor.

Extracts SEO keywords from product data: primary keywords, secondary keywords,
long-tail phrases, and related terms.

No model dependency — deterministic extraction from product data.
"""
from __future__ import annotations

import copy
import re
from typing import Any


# ---------------------------------------------------------------------------
# Stop words to exclude from keyword extraction
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "been", "has", "have", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "my", "your", "his",
    "her", "its", "our", "their", "not", "no", "so", "if", "up", "out",
    "just", "about", "very", "also", "more", "than", "then", "into",
}

# Default target keyword density (percentage)
_DEFAULT_TARGET_DENSITY = 1.5


def extract_keywords(
    product: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, Any]:
    """Extract SEO keywords from product and brand data.

    Args:
        product: ProductData dict with title, features, category, target_audience.
        brand: BrandData dict with name, voice, values.

    Returns:
        Structured dict with KeywordExtraction data.
    """
    try:
        prod = copy.deepcopy(product)
        brnd = copy.deepcopy(brand)

        title = str(prod.get("title", "")).strip()
        features = list(prod.get("features", []))
        category = str(prod.get("category", "")).strip().lower()
        target_audience = str(prod.get("target_audience", "")).strip().lower()
        brand_name = str(brnd.get("name", "")).strip()

        # --- Primary keywords: from title ---
        title_words = _clean_words(title)
        primary_keywords = title_words[:5] if title_words else [category] if category else ["product"]

        # --- Secondary keywords: from features ---
        feature_words: list[str] = []
        for feat in features:
            feature_words.extend(_clean_words(feat))
        # Deduplicate while preserving order, exclude primary
        primary_set = set(primary_keywords)
        seen: set[str] = set()
        secondary_keywords: list[str] = []
        for w in feature_words:
            if w not in primary_set and w not in seen:
                seen.add(w)
                secondary_keywords.append(w)
        secondary_keywords = secondary_keywords[:8]

        # --- Long-tail keywords: combine title + category + audience ---
        long_tail_keywords = _build_long_tail(title, category, target_audience, features)

        # --- Related terms: brand, category, audience ---
        related_terms = _build_related_terms(brand_name, category, target_audience, features)

        return {
            "status": "success",
            "extraction": {
                "primary_keywords": primary_keywords,
                "secondary_keywords": secondary_keywords,
                "long_tail_keywords": long_tail_keywords,
                "related_terms": related_terms,
                "target_density": _DEFAULT_TARGET_DENSITY,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "extraction": {},
            "error": f"Keyword extraction failed: {exc}",
        }


def _clean_words(text: str) -> list[str]:
    """Extract meaningful words from text, removing stop words and noise."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _build_long_tail(title: str, category: str, audience: str, features: list[str]) -> list[str]:
    """Build long-tail keyword phrases."""
    long_tails: list[str] = []

    title_clean = title.strip()
    if title_clean and category:
        long_tails.append(f"best {category} {title_clean.lower()}")
    if title_clean and audience:
        long_tails.append(f"{title_clean.lower()} for {audience}")
    if category and audience:
        long_tails.append(f"{category} for {audience}")

    # Feature-based long-tails
    for feat in features[:2]:
        feat_clean = feat.strip().lower()
        if feat_clean and category:
            long_tails.append(f"{category} with {feat_clean}")

    return long_tails[:5]


def _build_related_terms(brand_name: str, category: str, audience: str, features: list[str]) -> list[str]:
    """Build related search terms."""
    terms: list[str] = []
    if brand_name:
        terms.append(brand_name.lower())
    if category:
        terms.append(f"{category} shop")
        terms.append(f"buy {category}")
    if audience:
        terms.append(f"{audience} essentials")

    # Add feature-derived terms
    for feat in features[:2]:
        words = _clean_words(feat)
        if words:
            terms.append(words[0])

    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:6]
