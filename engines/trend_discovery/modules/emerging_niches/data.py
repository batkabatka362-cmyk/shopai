"""Emerging niches data — known niches, signal weights, lifecycle stages."""
from __future__ import annotations
from typing import Any

# Signal type weights for niche scoring
SIGNAL_WEIGHTS: dict[str, float] = {
    "search": 0.30,
    "social": 0.25,
    "funding": 0.20,
    "patents": 0.15,
    "media": 0.10,
}

# Known emerging niches 2025 with maturity and signal data
KNOWN_EMERGING_NICHES: list[dict[str, Any]] = [
    {
        "name": "AI-generated custom supplements",
        "maturity": "pre-market",
        "signals": {"search": 15, "social": 25, "funding": 40, "patents": 35, "media": 10},
        "trigger": "technology",
        "description": "Personalized supplement blends designed by AI from bloodwork data",
    },
    {
        "name": "Biodegradable phone cases from seaweed",
        "maturity": "early",
        "signals": {"search": 30, "social": 55, "funding": 20, "patents": 10, "media": 35},
        "trigger": "cultural_shift",
        "description": "Zero-waste phone accessories made from ocean-harvested algae",
    },
    {
        "name": "Pet anxiety wearables",
        "maturity": "early",
        "signals": {"search": 45, "social": 60, "funding": 30, "patents": 25, "media": 20},
        "trigger": "technology",
        "description": "Smart collars and vests that detect and soothe pet stress",
    },
    {
        "name": "Carbon-negative home goods",
        "maturity": "growing",
        "signals": {"search": 55, "social": 50, "funding": 60, "patents": 20, "media": 65},
        "trigger": "regulation",
        "description": "Household products that remove more CO2 than they create",
    },
    {
        "name": "Mushroom-based leather accessories",
        "maturity": "growing",
        "signals": {"search": 60, "social": 45, "funding": 55, "patents": 40, "media": 50},
        "trigger": "cultural_shift",
        "description": "Wallets, bags, belts made from mycelium leather",
    },
    {
        "name": "Neuro-focus desk accessories",
        "maturity": "pre-market",
        "signals": {"search": 10, "social": 20, "funding": 15, "patents": 30, "media": 5},
        "trigger": "technology",
        "description": "Desk tools designed around neuroscience focus principles",
    },
    {
        "name": "Solar-powered personal gadgets",
        "maturity": "early",
        "signals": {"search": 40, "social": 35, "funding": 45, "patents": 50, "media": 25},
        "trigger": "regulation",
        "description": "Small electronics with integrated solar charging (earbuds, watches)",
    },
    {
        "name": "Adaptive clothing for disabled consumers",
        "maturity": "growing",
        "signals": {"search": 50, "social": 70, "funding": 35, "patents": 15, "media": 55},
        "trigger": "cultural_shift",
        "description": "Fashionable clothing with magnetic closures and seated cuts",
    },
]

# Niche lifecycle stages with typical durations and characteristics
NICHE_LIFECYCLE_STAGES: dict[str, dict[str, Any]] = {
    "pre-market": {
        "duration_months": (6, 24),
        "search_volume": "< 1000/mo",
        "competition": "near zero",
        "margin_potential": "very high (60-80%)",
        "risk": "high — niche may never materialize",
        "strategy": "Build audience, create content, test with micro-products",
    },
    "early": {
        "duration_months": (6, 18),
        "search_volume": "1000 - 10000/mo",
        "competition": "1-5 serious players",
        "margin_potential": "high (40-60%)",
        "risk": "medium — niche is forming but direction unclear",
        "strategy": "Launch MVP product, build brand authority, capture email list",
    },
    "growing": {
        "duration_months": (12, 36),
        "search_volume": "10000 - 100000/mo",
        "competition": "5-20 players, some well-funded",
        "margin_potential": "medium (25-45%)",
        "risk": "lower — validated demand, but competition rising",
        "strategy": "Scale proven products, differentiate on brand/quality, expand SKUs",
    },
    "mainstream": {
        "duration_months": (24, 60),
        "search_volume": "> 100000/mo",
        "competition": "saturated, big brands entering",
        "margin_potential": "low (10-25%)",
        "risk": "low demand risk, high margin risk",
        "strategy": "Compete on operations/brand or exit to next niche",
    },
}

# Trigger event types and their typical niche formation speed
TRIGGER_SPEEDS: dict[str, dict[str, Any]] = {
    "regulation": {"speed": "slow", "months_to_impact": (6, 18), "predictability": "high"},
    "technology": {"speed": "medium", "months_to_impact": (3, 12), "predictability": "medium"},
    "cultural_shift": {"speed": "fast", "months_to_impact": (1, 6), "predictability": "low"},
    "viral_event": {"speed": "very_fast", "months_to_impact": (0, 3), "predictability": "very_low"},
}


def get_emerging_niches(maturity: str | None = None) -> list[dict[str, Any]]:
    """Return known emerging niches, optionally filtered by maturity stage."""
    if maturity is None:
        return KNOWN_EMERGING_NICHES
    return [n for n in KNOWN_EMERGING_NICHES if n["maturity"] == maturity]


def get_trigger_info(trigger_type: str) -> dict[str, Any]:
    """Get info about how quickly a trigger type forms niches."""
    return TRIGGER_SPEEDS.get(trigger_type, TRIGGER_SPEEDS["cultural_shift"])
