"""FTC advertising compliance — prohibited claims, endorsement rules.

10 FTC rules encoded. Detects prohibited claims, scarcity misuse,
undisclosed endorsements, and price comparison issues.
"""
from __future__ import annotations

from typing import Any

from .product_compliance import PROHIBITED_CLAIMS


FTC_ADVERTISING_RULES = {
    "truthful": "All claims must be truthful and not misleading",
    "evidence": "Claims must be backed by evidence before making them",
    "testimonials": "Testimonials must reflect typical results OR include disclaimer",
    "endorsements": "Paid endorsements must be disclosed (#ad, #sponsored)",
    "pricing": "Sale prices must reference genuine former prices",
    "scarcity": "'Limited stock' claims must be truthful",
    "guarantees": "Money-back guarantees must be honored as stated",
    "free": "'Free' items cannot increase the price of required purchase",
    "environmental": "Green/eco claims must be specific and substantiated",
    "made_in": "'Made in USA' requires all/virtually all manufacturing in US",
}


def check_advertising(content: str) -> dict[str, Any]:
    """Check advertising content for FTC compliance."""
    content_lower = content.lower()
    violations = []
    warnings = []

    for claim in PROHIBITED_CLAIMS:
        if claim in content_lower:
            violations.append(f"Prohibited claim detected: '{claim}'")

    scarcity_words = ["limited time", "only x left", "selling fast", "almost gone", "last chance"]
    for word in scarcity_words:
        if word in content_lower:
            warnings.append(f"Scarcity claim '{word}' — must be truthful per FTC guidelines")

    endorsement_words = ["influencer", "sponsored", "partner", "ambassador"]
    has_endorsement = any(w in content_lower for w in endorsement_words)
    has_disclosure = "#ad" in content_lower or "#sponsored" in content_lower or "paid partnership" in content_lower
    if has_endorsement and not has_disclosure:
        violations.append("Endorsement detected without required FTC disclosure (#ad/#sponsored)")

    if "was $" in content_lower or "originally $" in content_lower or "save $" in content_lower:
        warnings.append("Price comparison — ensure former price was genuine and recent")

    return {
        "content_preview": content[:100] + ("..." if len(content) > 100 else ""),
        "compliant": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "ftc_rules_reference": list(FTC_ADVERTISING_RULES.keys()),
    }
