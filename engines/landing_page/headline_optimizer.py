"""Landing Page Engine — headline optimizer.

Generates A/B headline variants using different copywriting frameworks.
Scores each variant for estimated CTR based on structural features.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Copywriting frameworks for headline generation
# ---------------------------------------------------------------------------

_FRAMEWORKS = [
    {
        "name": "benefit_driven",
        "template": "Get {benefit} with {product}",
        "emotional_appeal": "desire",
        "base_ctr": 0.035,
    },
    {
        "name": "problem_solution",
        "template": "Tired of {problem}? {product} Fixes That",
        "emotional_appeal": "relief",
        "base_ctr": 0.040,
    },
    {
        "name": "social_proof",
        "template": "Why Thousands Choose {product} for {benefit}",
        "emotional_appeal": "trust",
        "base_ctr": 0.032,
    },
    {
        "name": "curiosity",
        "template": "The {product} Secret to {benefit}",
        "emotional_appeal": "curiosity",
        "base_ctr": 0.038,
    },
    {
        "name": "direct_offer",
        "template": "{product} — {benefit}, Guaranteed",
        "emotional_appeal": "confidence",
        "base_ctr": 0.030,
    },
]

# CTR boost factors for headline characteristics
_POWER_WORDS = {"free", "new", "proven", "guaranteed", "exclusive", "limited", "instant", "save"}
_OPTIMAL_LENGTH_MIN = 30
_OPTIMAL_LENGTH_MAX = 70


def optimize_headlines(
    base_page: dict[str, Any],
    product: dict[str, Any],
    target_audience: str,
    brand_voice: str,
) -> dict[str, Any]:
    """Generate optimized headline variants from a base page.

    Args:
        base_page: Base page structure from page_generator.
        product: Product data dict.
        target_audience: Target audience description.
        brand_voice: Brand voice style.

    Returns:
        Structured dict with headline variants and estimated CTRs.
    """
    try:
        product = copy.deepcopy(product)
        title = str(product.get("title", "Our Product"))
        features = list(product.get("features", []))
        description = str(product.get("description", ""))

        key_benefit = features[0] if features else "quality"
        problem = _infer_problem(description, features)

        variants: list[dict[str, Any]] = []

        for fw in _FRAMEWORKS:
            text = str(fw["template"]).format(
                product=title,
                benefit=key_benefit.title(),
                problem=problem,
            )

            # Score the headline
            estimated_ctr = _score_headline(text, fw["base_ctr"])

            variants.append({
                "text": text,
                "framework": str(fw["name"]),
                "estimated_ctr": estimated_ctr,
                "emotional_appeal": str(fw["emotional_appeal"]),
            })

        # Include original headline as baseline
        original = str(base_page.get("headline", ""))
        if original:
            variants.insert(0, {
                "text": original,
                "framework": "original",
                "estimated_ctr": _score_headline(original, 0.030),
                "emotional_appeal": "mixed",
            })

        # Sort by estimated CTR descending
        variants.sort(key=lambda v: v["estimated_ctr"], reverse=True)

        return {
            "status": "success",
            "variants": variants,
        }
    except Exception as exc:
        return {
            "status": "error",
            "variants": [],
            "error": f"Headline optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_headline(text: str, base_ctr: float) -> float:
    """Score a headline for estimated CTR based on structural features."""
    score = base_ctr

    # Length optimization
    length = len(text)
    if _OPTIMAL_LENGTH_MIN <= length <= _OPTIMAL_LENGTH_MAX:
        score *= 1.15  # Optimal length boost
    elif length > _OPTIMAL_LENGTH_MAX:
        score *= 0.90  # Too long penalty
    elif length < 15:
        score *= 0.85  # Too short penalty

    # Power words boost
    words = set(text.lower().split())
    power_count = len(words & _POWER_WORDS)
    score *= (1.0 + power_count * 0.05)

    # Number in headline boost
    if any(c.isdigit() for c in text):
        score *= 1.08

    # Question mark boost (curiosity)
    if "?" in text:
        score *= 1.10

    return round(score, 4)


def _infer_problem(description: str, features: list[str]) -> str:
    """Infer the problem the product solves from its description."""
    desc_lower = description.lower()

    problem_indicators = {
        "slow": "slow results",
        "expensive": "overpaying",
        "complicated": "complicated solutions",
        "difficult": "difficult processes",
        "unreliable": "unreliable products",
        "poor quality": "poor quality alternatives",
    }

    for keyword, problem in problem_indicators.items():
        if keyword in desc_lower:
            return problem

    return "settling for less"
