"""Emerging niches domain knowledge — expert intelligence on niche discovery.

What veterans know:
  - "The best niches solve problems people don't know they have yet"
  - "Crowdfunding success (Kickstarter/Indiegogo) = 6-12 month product opportunity"
  - "Patent filing clusters = industry preparing for new category"
  - "If Reddit is talking about it but Amazon doesn't have it, you have a window"
"""
from __future__ import annotations
from typing import Any


NICHE_HEURISTICS: list[str] = [
    "The best niches solve problems people don't know they have yet",
    "Crowdfunding success (Kickstarter/Indiegogo) = 6-12 month product opportunity",
    "Patent filing clusters = industry preparing for new category",
    "If Reddit is talking about it but Amazon doesn't have it, you have a 6-month window",
    "A niche driven by a single viral event will die in 3 months — don't chase it",
    "B2B niches are slower to form but stickier than B2C",
    "3+ funded startups in same space = venture capital validating the niche",
    "Government regulation announcements create niches 12-18 months before enforcement",
    "When mainstream media covers a niche, you're already 6 months late",
    "Subreddit growth rate > 10%/month = community forming around a problem",
    "TikTok virality without search volume = curiosity, not demand — wait for search to follow",
    "The sweet spot: search growing 30-80% YoY, fewer than 5 Amazon competitors, active subreddit",
]

# How to validate a niche with a $200 test budget
VALIDATION_PLAYBOOK: dict[str, Any] = {
    "budget": 200,
    "currency": "USD",
    "duration_days": 14,
    "steps": [
        {
            "step": 1,
            "action": "Create a landing page with product concept",
            "cost": 0,
            "tools": "Carrd.co free tier or single-page HTML",
            "success_metric": "Page loads and looks credible",
        },
        {
            "step": 2,
            "action": "Run $80 in Facebook/Instagram ads targeting the niche audience",
            "cost": 80,
            "tools": "Meta Ads Manager, target interest-based audiences",
            "success_metric": "CTR > 2%, CPC < $1.50",
        },
        {
            "step": 3,
            "action": "Run $60 in Google Search ads on niche keywords",
            "cost": 60,
            "tools": "Google Ads, exact match on 5-10 keywords",
            "success_metric": "CTR > 3%, conversions (email signups) > 5",
        },
        {
            "step": 4,
            "action": "Post in 3-5 relevant Reddit/Facebook communities asking about the problem",
            "cost": 0,
            "tools": "Reddit, Facebook Groups",
            "success_metric": "10+ engaged replies, people describing the problem",
        },
        {
            "step": 5,
            "action": "Run $40 in TikTok/YouTube shorts testing product concept video",
            "cost": 40,
            "tools": "TikTok Ads or YouTube Shorts promotion",
            "success_metric": "View-through rate > 15%, positive comments",
        },
        {
            "step": 6,
            "action": "Collect email signups with 'notify me when available' CTA",
            "cost": 20,
            "tools": "Mailchimp free tier for email capture",
            "success_metric": "20+ signups = validated, 50+ = strong signal",
        },
    ],
    "go_threshold": "20+ email signups AND positive community feedback",
    "no_go_threshold": "< 5 signups AND CTR < 1% on ads",
    "maybe_threshold": "5-19 signups — retest with different angle or audience",
}

NICHE_SIGNAL_INTERPRETATION: dict[str, dict[str, str]] = {
    "search_rising_social_flat": {
        "meaning": "People searching but not talking — functional need, not exciting",
        "action": "Good for utility products, skip lifestyle branding",
    },
    "social_rising_search_flat": {
        "meaning": "Buzz without demand — may be awareness-stage only",
        "action": "Wait 3 months for search to follow, or it's just hype",
    },
    "both_rising": {
        "meaning": "Real emerging demand — people talking AND searching",
        "action": "Move fast, this is the ideal entry signal",
    },
    "funding_rising_rest_flat": {
        "meaning": "VCs see opportunity but consumers aren't there yet",
        "action": "12-18 month horizon, build audience now, launch product later",
    },
    "patents_rising_rest_flat": {
        "meaning": "Industry R&D active — new category forming quietly",
        "action": "Monitor for 6 months, prepare supply chain relationships",
    },
}


def get_niche_heuristics() -> list[str]:
    """Return expert heuristics for niche evaluation."""
    return NICHE_HEURISTICS


def get_validation_playbook() -> dict[str, Any]:
    """Return the $200 niche validation playbook."""
    return VALIDATION_PLAYBOOK


def interpret_signal_pattern(search_trend: str, social_trend: str,
                              funding_trend: str = "flat",
                              patents_trend: str = "flat") -> dict[str, str]:
    """Interpret a combination of signal trends."""
    if search_trend == "rising" and social_trend == "rising":
        return NICHE_SIGNAL_INTERPRETATION["both_rising"]
    if search_trend == "rising" and social_trend == "flat":
        return NICHE_SIGNAL_INTERPRETATION["search_rising_social_flat"]
    if social_trend == "rising" and search_trend == "flat":
        return NICHE_SIGNAL_INTERPRETATION["social_rising_search_flat"]
    if funding_trend == "rising" and search_trend == "flat" and social_trend == "flat":
        return NICHE_SIGNAL_INTERPRETATION["funding_rising_rest_flat"]
    if patents_trend == "rising" and search_trend == "flat" and social_trend == "flat":
        return NICHE_SIGNAL_INTERPRETATION["patents_rising_rest_flat"]
    return {"meaning": "No clear pattern — insufficient signal", "action": "Gather more data"}
