"""Landing Page Engine — performance scorer.

Scores landing page variants on conversion effectiveness based on
structural elements, content quality, and CRO best practices.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Scoring weights for page elements
# ---------------------------------------------------------------------------

_ELEMENT_WEIGHTS = {
    "headline": 0.20,
    "subheadline": 0.10,
    "hero_section": 0.15,
    "benefits": 0.20,
    "cta": 0.20,
    "social_proof": 0.15,
}

# Ideal content length ranges
_IDEAL_HEADLINE_LEN = (30, 70)
_IDEAL_SUBHEADLINE_LEN = (40, 120)
_IDEAL_BENEFITS_COUNT = (3, 6)


def score_performance(
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score landing page variants for conversion effectiveness.

    Args:
        pages: List of page variant dicts.

    Returns:
        Structured dict with scores per page variant.
    """
    try:
        pages = copy.deepcopy(pages)
        scores: list[dict[str, Any]] = []

        for page in pages:
            headline = str(page.get("headline", ""))
            subheadline = str(page.get("subheadline", ""))
            hero_section = str(page.get("hero_section", ""))
            benefits = list(page.get("benefits", []))
            cta = str(page.get("cta", ""))
            social_proof = str(page.get("social_proof", ""))

            # Score each element
            headline_score = _score_headline(headline)
            subheadline_score = _score_subheadline(subheadline)
            hero_score = _score_hero(hero_section)
            benefits_score = _score_benefits(benefits)
            cta_score = _score_cta(cta)
            social_score = _score_social_proof(social_proof)

            # Weighted overall score
            overall = (
                headline_score * _ELEMENT_WEIGHTS["headline"]
                + subheadline_score * _ELEMENT_WEIGHTS["subheadline"]
                + hero_score * _ELEMENT_WEIGHTS["hero_section"]
                + benefits_score * _ELEMENT_WEIGHTS["benefits"]
                + cta_score * _ELEMENT_WEIGHTS["cta"]
                + social_score * _ELEMENT_WEIGHTS["social_proof"]
            )

            # Mobile readiness heuristic
            total_text_len = len(headline) + len(subheadline) + len(hero_section) + len(cta)
            mobile_readiness = 1.0 if total_text_len < 400 else 0.7

            scores.append({
                "overall": round(overall, 4),
                "headline_score": round(headline_score, 4),
                "cta_score": round(cta_score, 4),
                "social_proof_score": round(social_score, 4),
                "mobile_readiness": round(mobile_readiness, 4),
                "load_speed_estimate": "fast" if len(benefits) <= 5 else "moderate",
            })

        return {
            "status": "success",
            "scores": scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "scores": [],
            "error": f"Performance scoring failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal scoring functions
# ---------------------------------------------------------------------------

def _score_headline(text: str) -> float:
    """Score a headline for effectiveness (0.0 to 1.0)."""
    if not text:
        return 0.0

    score = 0.5  # Base score for having a headline

    length = len(text)
    if _IDEAL_HEADLINE_LEN[0] <= length <= _IDEAL_HEADLINE_LEN[1]:
        score += 0.25
    elif length < _IDEAL_HEADLINE_LEN[0]:
        score += 0.10
    else:
        score += 0.15

    # Specificity: does it contain a number or specific claim?
    if any(c.isdigit() for c in text):
        score += 0.15
    elif any(w in text.lower() for w in ["best", "top", "leading", "proven"]):
        score += 0.10
    else:
        score += 0.05

    return min(score, 1.0)


def _score_subheadline(text: str) -> float:
    """Score subheadline for supporting the headline."""
    if not text:
        return 0.0

    score = 0.5
    length = len(text)
    if _IDEAL_SUBHEADLINE_LEN[0] <= length <= _IDEAL_SUBHEADLINE_LEN[1]:
        score += 0.3
    else:
        score += 0.15

    # Ends with period (complete thought)
    if text.endswith(".") or text.endswith("!"):
        score += 0.1

    return min(score, 1.0)


def _score_hero(text: str) -> float:
    """Score hero section content."""
    if not text:
        return 0.0

    score = 0.4
    if len(text) >= 50:
        score += 0.3
    if "$" in text or "free" in text.lower():
        score += 0.2
    else:
        score += 0.1

    return min(score, 1.0)


def _score_benefits(benefits: list[str]) -> float:
    """Score the benefits list."""
    if not benefits:
        return 0.0

    count = len(benefits)
    score = 0.3

    if _IDEAL_BENEFITS_COUNT[0] <= count <= _IDEAL_BENEFITS_COUNT[1]:
        score += 0.4
    elif count < _IDEAL_BENEFITS_COUNT[0]:
        score += 0.2
    else:
        score += 0.25

    # Quality: each benefit should be substantive
    substantive = sum(1 for b in benefits if len(str(b)) >= 15)
    if substantive == count:
        score += 0.3
    else:
        score += 0.15

    return min(score, 1.0)


def _score_cta(text: str) -> float:
    """Score a CTA for conversion potential."""
    if not text:
        return 0.0

    score = 0.4

    # Length: short CTAs perform better
    length = len(text)
    if 5 <= length <= 25:
        score += 0.3
    elif length < 5:
        score += 0.15
    else:
        score += 0.1

    # Action verbs
    action_verbs = {"get", "buy", "start", "try", "claim", "join", "shop", "discover", "explore", "unlock"}
    first_word = text.split()[0].lower() if text.split() else ""
    if first_word in action_verbs:
        score += 0.2
    else:
        score += 0.05

    return min(score, 1.0)


def _score_social_proof(text: str) -> float:
    """Score the social proof element."""
    if not text:
        return 0.0

    score = 0.4

    # Specificity indicators
    if any(c.isdigit() for c in text):
        score += 0.3  # Contains numbers (e.g., "10,000 customers")
    elif any(w in text.lower() for w in ["thousands", "hundreds", "millions"]):
        score += 0.2

    if any(w in text.lower() for w in ["trusted", "rated", "reviewed", "featured"]):
        score += 0.15

    return min(score, 1.0)
