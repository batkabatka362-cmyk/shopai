"""Reference data for legal risk assessment.

Regulatory requirements, compliance costs, IP pitfalls, liability
insurance rates, and platform policy restrictions. All costs in USD.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Regulatory requirements by product category
# ---------------------------------------------------------------------------
REGULATORY_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "supplements": {
        "agencies": ["FDA"],
        "requirements": ["GMP certification", "supplement facts label", "DSHEA compliance"],
        "timeline_months": (3, 6),
        "mandatory": True,
    },
    "cosmetics": {
        "agencies": ["FDA"],
        "requirements": ["ingredient disclosure", "MoCRA registration", "safety substantiation"],
        "timeline_months": (2, 4),
        "mandatory": True,
    },
    "electronics": {
        "agencies": ["FCC"],
        "requirements": ["FCC certification", "UL listing recommended", "EMC testing"],
        "timeline_months": (2, 5),
        "mandatory": True,
    },
    "children_products": {
        "agencies": ["CPSC"],
        "requirements": ["CPSIA testing", "lead/phthalate limits", "tracking labels", "CPC certificate"],
        "timeline_months": (2, 4),
        "mandatory": True,
    },
    "children_toys": {
        "agencies": ["CPSC", "ASTM"],
        "requirements": ["ASTM F963 testing", "small parts test", "CPC certificate", "age grading"],
        "timeline_months": (3, 5),
        "mandatory": True,
    },
    "food": {
        "agencies": ["FDA"],
        "requirements": ["FDA facility registration", "nutrition facts label", "HACCP plan", "allergen labeling"],
        "timeline_months": (3, 6),
        "mandatory": True,
    },
    "medical_devices": {
        "agencies": ["FDA"],
        "requirements": ["510(k) clearance or De Novo", "QSR compliance", "MDR reporting"],
        "timeline_months": (6, 18),
        "mandatory": True,
    },
    "clothing": {
        "agencies": ["FTC"],
        "requirements": ["textile fiber content label", "care label", "country of origin"],
        "timeline_months": (0, 1),
        "mandatory": True,
    },
    "general": {
        "agencies": [],
        "requirements": ["general product safety", "proper labeling"],
        "timeline_months": (0, 1),
        "mandatory": False,
    },
}

# ---------------------------------------------------------------------------
# Compliance cost ranges by agency/certification (USD)
# ---------------------------------------------------------------------------
COMPLIANCE_COST_RANGES: dict[str, dict[str, Any]] = {
    "fda_supplement": {"low": 3000, "high": 10000, "description": "FDA supplement compliance and GMP"},
    "fda_cosmetic": {"low": 2000, "high": 8000, "description": "FDA cosmetic MoCRA registration"},
    "fda_food": {"low": 3000, "high": 15000, "description": "FDA food facility and labeling"},
    "fda_medical_device": {"low": 15000, "high": 150000, "description": "FDA 510(k) or De Novo pathway"},
    "fcc_certification": {"low": 2000, "high": 8000, "description": "FCC intentional/unintentional radiator testing"},
    "cpsc_testing": {"low": 1500, "high": 6000, "description": "CPSC children's product testing and CPC"},
    "ul_listing": {"low": 5000, "high": 25000, "description": "UL safety listing for electronics"},
    "astm_toy_testing": {"low": 1000, "high": 4000, "description": "ASTM F963 toy safety testing"},
    "ftc_textile_label": {"low": 200, "high": 800, "description": "FTC textile and care label compliance"},
    "patent_search": {"low": 1500, "high": 5000, "description": "Professional patent clearance search"},
    "trademark_registration": {"low": 250, "high": 2000, "description": "USPTO trademark filing and registration"},
}

# ---------------------------------------------------------------------------
# Common IP pitfalls by product type
# ---------------------------------------------------------------------------
COMMON_IP_PITFALLS: list[dict[str, Any]] = [
    {"category": "phone_accessories", "risk": "design patent infringement", "detail": "Apple/Samsung design patents on case shapes and features", "frequency": "high"},
    {"category": "kitchen_gadgets", "risk": "utility patent infringement", "detail": "Many simple kitchen tools have active utility patents", "frequency": "high"},
    {"category": "fitness_equipment", "risk": "trade dress infringement", "detail": "Recognizable product shapes (e.g., Peloton, Bowflex)", "frequency": "medium"},
    {"category": "toys", "risk": "copyright/trademark infringement", "detail": "Character licensing violations extremely common", "frequency": "very_high"},
    {"category": "electronics", "risk": "patent trolls", "detail": "Broad software/method patents used for demand letters", "frequency": "high"},
    {"category": "clothing", "risk": "trademark counterfeiting", "detail": "Brand name and logo infringement on fast fashion", "frequency": "very_high"},
    {"category": "supplements", "risk": "false health claims", "detail": "FTC enforcement on unsubstantiated claims", "frequency": "high"},
    {"category": "beauty", "risk": "trade secret misappropriation", "detail": "Formula copying from established brands", "frequency": "medium"},
]

# ---------------------------------------------------------------------------
# Product liability insurance rates (annual, USD)
# ---------------------------------------------------------------------------
LIABILITY_INSURANCE_RATES: dict[str, dict[str, Any]] = {
    "low_risk": {"annual_premium": (500, 1000), "categories": ["clothing", "accessories", "home_decor"], "coverage": 1000000},
    "medium_risk": {"annual_premium": (1000, 2000), "categories": ["general", "kitchen", "pet_products"], "coverage": 1000000},
    "high_risk": {"annual_premium": (2000, 5000), "categories": ["electronics", "supplements", "cosmetics"], "coverage": 1000000},
    "very_high_risk": {"annual_premium": (5000, 15000), "categories": ["children_products", "food", "sporting_goods"], "coverage": 1000000},
}

# ---------------------------------------------------------------------------
# Platform policy restrictions (Amazon, Shopify, etc.)
# ---------------------------------------------------------------------------
PLATFORM_POLICY_RESTRICTIONS: dict[str, list[dict[str, str]]] = {
    "amazon": [
        {"category": "supplements", "restriction": "Requires FDA compliance documentation on file"},
        {"category": "pesticides", "restriction": "Restricted — requires EPA registration"},
        {"category": "weapons", "restriction": "Prohibited on marketplace"},
        {"category": "alcohol", "restriction": "Restricted — state-by-state licensing"},
        {"category": "cbd", "restriction": "Prohibited — topical CBD only in select regions"},
        {"category": "tobacco", "restriction": "Prohibited on marketplace"},
    ],
    "shopify": [
        {"category": "firearms", "restriction": "Prohibited under Shopify Payments"},
        {"category": "cbd", "restriction": "Allowed with compliant payment processor"},
        {"category": "adult", "restriction": "Allowed with age gate — restricted from Shopify Payments"},
    ],
    "walmart": [
        {"category": "supplements", "restriction": "Requires third-party testing documentation"},
        {"category": "weapons", "restriction": "Prohibited on marketplace"},
        {"category": "alcohol", "restriction": "Prohibited on marketplace"},
    ],
}


def get_regulatory_requirements(category: str) -> dict[str, Any]:
    """Return regulatory requirements for a product category."""
    return REGULATORY_REQUIREMENTS.get(category, REGULATORY_REQUIREMENTS["general"])


def get_compliance_cost(certification: str) -> dict[str, Any]:
    """Return compliance cost range for a given certification type."""
    return COMPLIANCE_COST_RANGES.get(certification, {"low": 0, "high": 0, "description": "Unknown certification"})


def get_liability_tier(category: str) -> str:
    """Return the liability tier for a product category."""
    for tier, info in LIABILITY_INSURANCE_RATES.items():
        if category in info["categories"]:
            return tier
    return "medium_risk"
