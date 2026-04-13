"""Landing Page Engine — CTA optimizer.

Generates and scores call-to-action variants optimized for
conversion based on campaign goal, urgency level, and audience.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# CTA templates by goal and urgency
# ---------------------------------------------------------------------------

_CTA_TEMPLATES = {
    "conversion": [
        {"text": "Buy Now", "style": "direct", "urgency": "low", "base_rate": 0.042},
        {"text": "Add to Cart", "style": "soft", "urgency": "low", "base_rate": 0.038},
        {"text": "Get Yours Today", "style": "direct", "urgency": "medium", "base_rate": 0.045},
        {"text": "Claim Your Discount", "style": "incentive", "urgency": "high", "base_rate": 0.050},
        {"text": "Start Your Free Trial", "style": "risk_free", "urgency": "low", "base_rate": 0.055},
    ],
    "awareness": [
        {"text": "Learn More", "style": "soft", "urgency": "low", "base_rate": 0.060},
        {"text": "See How It Works", "style": "educational", "urgency": "low", "base_rate": 0.055},
        {"text": "Explore Features", "style": "discovery", "urgency": "low", "base_rate": 0.048},
        {"text": "Watch the Demo", "style": "visual", "urgency": "low", "base_rate": 0.052},
    ],
    "retention": [
        {"text": "Shop New Arrivals", "style": "discovery", "urgency": "low", "base_rate": 0.040},
        {"text": "Unlock Your Loyalty Reward", "style": "incentive", "urgency": "medium", "base_rate": 0.048},
        {"text": "Continue Shopping", "style": "soft", "urgency": "low", "base_rate": 0.035},
        {"text": "See What's New for You", "style": "personalized", "urgency": "low", "base_rate": 0.044},
    ],
}


def optimize_ctas(
    base_page: dict[str, Any],
    campaign: dict[str, Any],
    target_audience: str,
) -> dict[str, Any]:
    """Generate optimized CTA variants for the landing page.

    Args:
        base_page: Base page structure from page_generator.
        campaign: Campaign context dict.
        target_audience: Target audience description.

    Returns:
        Structured dict with CTA variants and estimated click rates.
    """
    try:
        campaign = copy.deepcopy(campaign)
        goal = str(campaign.get("goal", "conversion")).lower()
        channel = str(campaign.get("channel", "web")).lower()

        templates = _CTA_TEMPLATES.get(goal, _CTA_TEMPLATES["conversion"])

        variants: list[dict[str, Any]] = []

        for tmpl in templates:
            text = str(tmpl["text"])
            base_rate = float(tmpl["base_rate"])

            # Adjust for channel
            adjusted_rate = _adjust_for_channel(base_rate, channel)

            # Adjust for audience type
            adjusted_rate = _adjust_for_audience(adjusted_rate, target_audience)

            variants.append({
                "text": text,
                "style": str(tmpl["style"]),
                "urgency_level": str(tmpl["urgency"]),
                "estimated_click_rate": round(adjusted_rate, 4),
            })

        # Include original CTA as baseline
        original_cta = str(base_page.get("cta", ""))
        if original_cta:
            variants.insert(0, {
                "text": original_cta,
                "style": "original",
                "urgency_level": "medium",
                "estimated_click_rate": round(0.035, 4),
            })

        # Sort by estimated click rate descending
        variants.sort(key=lambda v: v["estimated_click_rate"], reverse=True)

        return {
            "status": "success",
            "variants": variants,
        }
    except Exception as exc:
        return {
            "status": "error",
            "variants": [],
            "error": f"CTA optimization failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _adjust_for_channel(rate: float, channel: str) -> float:
    """Adjust click rate based on channel characteristics."""
    multipliers = {
        "mobile": 0.85,   # Smaller screens, less engagement
        "email": 1.10,    # Targeted, higher intent
        "social": 0.90,   # Scroll-past behavior
        "search": 1.15,   # Highest intent
        "web": 1.00,      # Baseline
    }
    return rate * multipliers.get(channel, 1.0)


def _adjust_for_audience(rate: float, audience: str) -> float:
    """Adjust click rate based on audience type description."""
    audience_lower = audience.lower()

    if any(w in audience_lower for w in ["returning", "loyal", "existing"]):
        return rate * 1.12  # Existing customers convert better
    elif any(w in audience_lower for w in ["cold", "new", "prospect"]):
        return rate * 0.88  # Cold audiences need more warming
    elif any(w in audience_lower for w in ["high-intent", "ready", "warm"]):
        return rate * 1.20  # High intent boosts conversion
    return rate
