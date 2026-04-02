"""Content Generation Engine — variation generator.

Generates content variations for A/B testing: alternative headlines, body
rewrites with different angles, and CTA variations.

No model dependency — rule-based variation generation.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Variation strategies
# ---------------------------------------------------------------------------

_VARIATION_FOCUSES = [
    "benefit_led",
    "urgency_led",
    "social_proof_led",
    "question_led",
]

_URGENCY_PREFIXES = [
    "Limited Time:",
    "Don't Miss Out:",
    "Act Now:",
    "Last Chance:",
]

_QUESTION_STARTERS = [
    "Looking for",
    "Ready for",
    "Want",
    "Need",
]

_SOCIAL_PROOF_PHRASES = [
    "Loved by thousands",
    "Top-rated",
    "Customer favorite",
    "Best-selling",
]

_CTA_VARIATIONS: dict[str, list[str]] = {
    "benefit_led": ["See the Benefits", "Discover Why", "Experience It Now"],
    "urgency_led": ["Grab It Now", "Don't Wait", "Order Today"],
    "social_proof_led": ["Join the Community", "See What Others Say", "Try What Works"],
    "question_led": ["Find Out More", "Get Your Answer", "Learn How"],
}


def generate_variations(
    draft: dict[str, Any],
    brief_analysis: dict[str, Any],
    max_variations: int = 3,
) -> dict[str, Any]:
    """Generate content variations for A/B testing.

    Args:
        draft: CopyDraft dict from copy_writer.
        brief_analysis: BriefAnalysis dict from brief_analyzer.
        max_variations: Maximum number of variations to generate.

    Returns:
        Structured dict with list of ContentVariation dicts.
    """
    try:
        drft = copy.deepcopy(draft)
        analysis = copy.deepcopy(brief_analysis)

        headline = str(drft.get("headline", ""))
        body = str(drft.get("body", ""))
        cta = str(drft.get("cta", ""))
        usps = list(analysis.get("usps", []))
        target_audience = str(analysis.get("target_audience", "consumers"))

        variations: list[dict[str, Any]] = []

        for i, focus in enumerate(_VARIATION_FOCUSES[:max_variations]):
            variant_id = uuid.uuid4().hex[:8]

            var_headline = _vary_headline(headline, focus, usps, target_audience)
            var_body = _vary_body(body, focus, usps)
            var_cta = _vary_cta(cta, focus)

            variations.append({
                "variant_id": variant_id,
                "headline": var_headline,
                "body": var_body,
                "cta": var_cta,
                "variation_focus": focus,
            })

        return {
            "status": "success",
            "variations": variations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "variations": [],
            "error": f"Variation generation failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Variation helpers
# ---------------------------------------------------------------------------

def _vary_headline(
    original: str,
    focus: str,
    usps: list[str],
    audience: str,
) -> str:
    """Create a headline variation based on focus strategy."""
    if focus == "benefit_led" and usps:
        return f"{usps[0].capitalize()} — {original.split('—')[0].strip()}" if "—" in original else f"{usps[0].capitalize()} | {original}"
    elif focus == "urgency_led":
        prefix = _URGENCY_PREFIXES[0]
        # Strip any existing prefix-like pattern
        core = original.split("—")[-1].strip() if "—" in original else original
        return f"{prefix} {core}"
    elif focus == "social_proof_led":
        phrase = _SOCIAL_PROOF_PHRASES[0]
        core = original.split("—")[0].strip() if "—" in original else original
        return f"{phrase} — {core}"
    elif focus == "question_led":
        starter = _QUESTION_STARTERS[0]
        # Build question from audience
        return f"{starter} the perfect solution? Discover {original.split('—')[0].strip()}"
    return original


def _vary_body(original: str, focus: str, usps: list[str]) -> str:
    """Create a body text variation based on focus strategy."""
    sentences = [s.strip() for s in original.split(". ") if s.strip()]
    if not sentences:
        return original

    if focus == "benefit_led" and usps:
        benefit_intro = f"The key benefit: {usps[0].strip().rstrip('.')}."
        return f"{benefit_intro} {'. '.join(sentences[1:])}" if len(sentences) > 1 else f"{benefit_intro} {original}"

    elif focus == "urgency_led":
        urgency_close = "This offer won't last — act before it's gone."
        trimmed = ". ".join(sentences[:max(len(sentences) - 1, 1)])
        if not trimmed.endswith("."):
            trimmed += "."
        return f"{trimmed} {urgency_close}"

    elif focus == "social_proof_led":
        proof_intro = "Thousands of customers already trust this choice."
        return f"{proof_intro} {original}"

    elif focus == "question_led":
        question = f"What if you could have it all?"
        return f"{question} {original}"

    return original


def _vary_cta(original: str, focus: str) -> str:
    """Select a CTA variation based on focus strategy."""
    options = _CTA_VARIATIONS.get(focus, [original])
    return options[0] if options else original
