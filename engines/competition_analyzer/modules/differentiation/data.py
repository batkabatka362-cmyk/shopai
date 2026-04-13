"""Differentiation data — strategy templates, cost ranges, and benchmarks.

Reference data for building and evaluating differentiation strategies.
"""
from __future__ import annotations

from typing import Any


# Strategy templates with actions and characteristics
STRATEGY_TEMPLATES = {
    "better_quality": {
        "name": "Better Quality",
        "description": "Differentiate by offering measurably superior product quality",
        "cost_level": "high",
        "actions": [
            "Source premium materials from vetted suppliers",
            "Implement quality control checkpoints",
            "Offer extended warranty or satisfaction guarantee",
            "Invest in professional product photography",
            "Collect and showcase quality-focused reviews",
        ],
        "best_for": "Categories where customers complain about quality",
        "avoid_when": "Market is purely price-driven with no quality seekers",
    },
    "better_service": {
        "name": "Better Service",
        "description": "Differentiate through exceptional customer experience",
        "cost_level": "medium",
        "actions": [
            "Respond to all inquiries within 4 hours",
            "Offer hassle-free returns beyond marketplace minimum",
            "Include personalized thank-you notes",
            "Proactive shipping updates and follow-ups",
            "Build FAQ and self-service resources",
        ],
        "best_for": "Categories where competitors have poor seller ratings",
        "avoid_when": "Product is low-touch commodity with no service expectations",
    },
    "niche_focus": {
        "name": "Niche Specialist",
        "description": "Own a specific sub-segment that generalists ignore",
        "cost_level": "low",
        "actions": [
            "Identify underserved sub-audience within the category",
            "Tailor product features to that specific audience",
            "Create content that speaks directly to the niche",
            "Build community around the niche use case",
            "Become the recognized expert for that segment",
        ],
        "best_for": "Broad categories dominated by generalist sellers",
        "avoid_when": "Niche is too small to sustain profitable volume",
    },
    "brand_story": {
        "name": "Brand Story",
        "description": "Differentiate through authentic brand narrative and values",
        "cost_level": "medium",
        "actions": [
            "Define a clear origin story and mission",
            "Consistent visual identity across all touchpoints",
            "Share behind-the-scenes content and process",
            "Align with values customers care about (sustainability, local, etc.)",
            "Build brand presence beyond the marketplace",
        ],
        "best_for": "Categories with many undifferentiated white-label sellers",
        "avoid_when": "Customers buy purely on specs and price (B2B commodities)",
    },
    "bundling": {
        "name": "Smart Bundling",
        "description": "Create unique value by combining products strategically",
        "cost_level": "low",
        "actions": [
            "Identify complementary products customers buy together",
            "Create bundles that save customers time and money",
            "Price bundles to show clear savings vs buying separately",
            "Test different bundle combinations with small batches",
            "Highlight bundle convenience in listing title",
        ],
        "best_for": "Categories with natural product pairings",
        "avoid_when": "Products have no logical pairing or bundles increase shipping cost",
    },
    "customization": {
        "name": "Customization",
        "description": "Offer personalized or configurable products",
        "cost_level": "high",
        "actions": [
            "Identify which product attributes customers want to customize",
            "Set up production workflow for custom orders",
            "Price customization at 30-50% premium over standard",
            "Offer preview/mockup before production",
            "Build a portfolio of customization examples",
        ],
        "best_for": "Gift categories, personal items, B2B with specific requirements",
        "avoid_when": "Product has no meaningful customizable attributes",
    },
}


# Implementation cost ranges in USD by dimension and impact level
IMPLEMENTATION_COST_RANGES = {
    "features": {
        "high": {"min": 5000, "max": 25000, "typical": 12000},
        "medium": {"min": 2000, "max": 8000, "typical": 4500},
        "low": {"min": 500, "max": 2000, "typical": 1000},
    },
    "service": {
        "high": {"min": 3000, "max": 15000, "typical": 8000},
        "medium": {"min": 1000, "max": 5000, "typical": 2500},
        "low": {"min": 200, "max": 1000, "typical": 500},
    },
    "brand": {
        "high": {"min": 8000, "max": 30000, "typical": 15000},
        "medium": {"min": 3000, "max": 10000, "typical": 5000},
        "low": {"min": 1000, "max": 3000, "typical": 1500},
    },
    "content": {
        "high": {"min": 4000, "max": 20000, "typical": 10000},
        "medium": {"min": 1500, "max": 6000, "typical": 3000},
        "low": {"min": 300, "max": 1500, "typical": 700},
    },
    "price": {
        "high": {"min": 2000, "max": 10000, "typical": 5000},
        "medium": {"min": 500, "max": 3000, "typical": 1500},
        "low": {"min": 100, "max": 500, "typical": 250},
    },
}


# Time to implement in months by dimension and impact level
TIME_TO_IMPLEMENT_ESTIMATES = {
    "features": {"high": 6, "medium": 3, "low": 1},
    "service": {"high": 3, "medium": 2, "low": 1},
    "brand": {"high": 9, "medium": 5, "low": 2},
    "content": {"high": 4, "medium": 2, "low": 1},
    "price": {"high": 2, "medium": 1, "low": 1},
}


# Sustainability ratings — how long until competitors copy?
SUSTAINABILITY_RATINGS = {
    "better_quality": {
        "months_defensible": 12,
        "copy_difficulty": "medium",
        "moat_type": "execution",
        "notes": "Quality can be copied but requires supplier relationships and QC investment",
    },
    "better_service": {
        "months_defensible": 18,
        "copy_difficulty": "medium",
        "moat_type": "culture",
        "notes": "Service culture is hard to fake — requires genuine commitment and systems",
    },
    "niche_focus": {
        "months_defensible": 15,
        "copy_difficulty": "medium",
        "moat_type": "expertise",
        "notes": "First-mover advantage in niche. Competitors must invest time to gain credibility",
    },
    "brand_story": {
        "months_defensible": 36,
        "copy_difficulty": "hard",
        "moat_type": "identity",
        "notes": "Authentic brand stories cannot be copied — they are inherently unique",
    },
    "bundling": {
        "months_defensible": 4,
        "copy_difficulty": "easy",
        "moat_type": "convenience",
        "notes": "Bundles are trivially easy to copy. Use as short-term tactic only.",
    },
    "customization": {
        "months_defensible": 14,
        "copy_difficulty": "medium",
        "moat_type": "operations",
        "notes": "Requires operational capability most sellers lack, but large players can invest",
    },
}


def get_strategy_template(strategy_type: str) -> dict[str, Any]:
    """Get the template for a specific differentiation strategy."""
    return STRATEGY_TEMPLATES.get(strategy_type, {
        "name": strategy_type,
        "description": "Custom strategy — define your own approach",
        "cost_level": "medium",
        "actions": ["Research and define a custom differentiation plan"],
        "best_for": "Varies",
        "avoid_when": "Unknown",
    })


def get_cost_range(dimension: str, impact_level: str) -> dict[str, Any]:
    """Get cost range for a specific dimension and impact level."""
    dim_costs = IMPLEMENTATION_COST_RANGES.get(dimension, {})
    return dim_costs.get(impact_level, {"min": 0, "max": 0, "typical": 0})
