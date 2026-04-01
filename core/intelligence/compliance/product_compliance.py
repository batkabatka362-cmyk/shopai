"""Product compliance — category-specific regulatory requirements.

6 regulated categories: supplements (FDA), cosmetics (FDA), food (FDA),
electronics (FCC), children (CPSC), textiles (FTC).
"""
from __future__ import annotations

from typing import Any

from .category_detector import detect_category


REGULATED_CATEGORIES = {
    "supplements": {
        "agency": "FDA",
        "requirements": [
            "Supplement Facts panel required",
            "No disease treatment/cure claims",
            "Disclaimer: 'These statements have not been evaluated by the FDA'",
            "GMP (Good Manufacturing Practice) certification",
            "Ingredient list with amounts",
        ],
        "risk": "high",
    },
    "cosmetics": {
        "agency": "FDA",
        "requirements": [
            "Ingredient list in descending order",
            "Net quantity of contents",
            "Name and place of business",
            "No drug claims (e.g., 'treats acne')",
            "Color additives must be FDA-approved",
        ],
        "risk": "medium",
    },
    "food": {
        "agency": "FDA",
        "requirements": [
            "Nutrition Facts label",
            "Allergen declarations (Big 9 allergens)",
            "Proper storage instructions",
            "Expiration/best-by date",
            "Facility registration with FDA",
        ],
        "risk": "high",
    },
    "electronics": {
        "agency": "FCC",
        "requirements": [
            "FCC compliance for devices that emit RF",
            "UL/ETL safety certification for plugged-in devices",
            "Proper labeling (FCC ID visible)",
            "Import documentation (if applicable)",
        ],
        "risk": "medium",
    },
    "children": {
        "agency": "CPSC",
        "requirements": [
            "CPSIA compliance (Consumer Product Safety Improvement Act)",
            "Lead content testing (<100 ppm)",
            "Phthalate testing for toys",
            "Small parts testing (choking hazard)",
            "Age grading and warning labels",
            "Children's Product Certificate (CPC)",
            "Tracking label (manufacturer, date, batch)",
        ],
        "risk": "critical",
    },
    "textiles": {
        "agency": "FTC",
        "requirements": [
            "Fiber content labeling (e.g., '100% Cotton')",
            "Country of origin",
            "Care instructions (washing/drying)",
            "Manufacturer/importer name",
        ],
        "risk": "low",
    },
}

PROHIBITED_CLAIMS = [
    "cure", "treat", "prevent", "diagnose",
    "guaranteed results", "100% effective",
    "FDA approved",
    "clinically proven",
    "risk-free",
    "miracle",
]


def check_product(product: dict[str, Any]) -> dict[str, Any]:
    """Check a product for category-specific compliance requirements."""
    category = detect_category(product)
    if not category:
        return {
            "product": product.get("title", product.get("name", "Unknown")),
            "category": "general",
            "compliant": True,
            "violations": [],
            "requirements": [],
            "note": "No specific regulatory requirements detected for this product category",
        }

    reg = REGULATED_CATEGORIES[category]
    violations = []
    requirements = reg["requirements"]

    title = (product.get("title", "") + " " + product.get("description", "")).lower()
    if category in ("supplements", "cosmetics", "food"):
        for claim in PROHIBITED_CLAIMS[:4]:
            if claim in title:
                violations.append(f"Contains prohibited claim: '{claim}' — {reg['agency']} violation")

    return {
        "product": product.get("title", product.get("name", "Unknown")),
        "category": category,
        "agency": reg["agency"],
        "risk_level": reg["risk"],
        "compliant": len(violations) == 0,
        "violations": violations,
        "requirements": requirements,
    }
