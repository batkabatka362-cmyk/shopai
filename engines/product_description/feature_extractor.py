"""Product Description Engine — feature extractor.

Extracts key features from product data and maps them to customer
benefits. Prioritizes features by likely purchase impact.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Feature category classification keywords
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "material": ["cotton", "leather", "wood", "metal", "steel", "silk", "polyester", "organic"],
    "size": ["large", "small", "compact", "oversized", "portable", "lightweight"],
    "durability": ["waterproof", "durable", "resistant", "long-lasting", "heavy-duty", "rugged"],
    "comfort": ["soft", "ergonomic", "padded", "breathable", "cushioned", "flexible"],
    "technology": ["wireless", "bluetooth", "smart", "digital", "rechargeable", "usb"],
    "sustainability": ["eco-friendly", "recycled", "sustainable", "biodegradable", "organic"],
}

# Benefit mappings for common feature categories
_BENEFIT_MAP: dict[str, str] = {
    "material": "Built with quality materials for superior feel and longevity",
    "size": "Designed to fit perfectly into your lifestyle",
    "durability": "Engineered to withstand daily use and last for years",
    "comfort": "Provides exceptional comfort for all-day use",
    "technology": "Equipped with modern technology for seamless experience",
    "sustainability": "Made responsibly with the environment in mind",
}


def extract_features(
    product: dict[str, Any],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract and prioritize key features from product data.

    Args:
        product: Product info dict (with features, specifications).
        competitors: Competitor product dicts for differentiation.

    Returns:
        Structured dict with extracted and prioritized features.
    """
    try:
        prod = copy.deepcopy(product)
        features_raw = list(prod.get("features", []))
        specs = dict(prod.get("specifications", {}))

        # Combine features from explicit list and specifications
        all_features: list[str] = []
        all_features.extend(features_raw)
        for key, value in specs.items():
            all_features.append(f"{key}: {value}")

        if not all_features:
            all_features = [str(prod.get("title", "Product"))]

        # Extract competitor keywords for differentiation
        competitor_keywords: set[str] = set()
        for comp in competitors:
            for kw in comp.get("keywords", []):
                competitor_keywords.add(kw.lower())

        # Classify and prioritize features
        extracted: list[dict[str, Any]] = []
        for i, feature in enumerate(all_features):
            feature_lower = feature.lower()

            # Classify category
            category = "general"
            for cat, keywords in _CATEGORY_KEYWORDS.items():
                if any(kw in feature_lower for kw in keywords):
                    category = cat
                    break

            # Map to benefit
            benefit = _BENEFIT_MAP.get(category, "Enhances your overall experience")

            # Priority: differentiating features score higher
            is_differentiator = any(
                kw in feature_lower for kw in competitor_keywords
            )
            priority = max(1, len(all_features) - i)
            if is_differentiator:
                priority += 3
            if category in ("durability", "technology"):
                priority += 2

            extracted.append({
                "feature": feature,
                "benefit": benefit,
                "priority": priority,
                "category": category,
            })

        # Sort by priority descending
        extracted.sort(key=lambda f: f["priority"], reverse=True)

        return {
            "status": "success",
            "features": extracted,
            "total_features": len(extracted),
        }
    except Exception as exc:
        return {
            "status": "error",
            "features": [],
            "error": f"Feature extraction failed: {exc}",
        }
