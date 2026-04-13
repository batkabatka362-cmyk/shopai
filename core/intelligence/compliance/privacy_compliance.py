"""Privacy compliance — GDPR, CCPA, COPPA requirements.

Determines which regulations apply based on selling geography
and customer demographics.
"""
from __future__ import annotations

from typing import Any


PRIVACY_REGULATIONS = {
    "gdpr": {
        "region": "EU/EEA",
        "requirements": [
            "Explicit consent for data collection",
            "Right to access personal data",
            "Right to deletion (right to be forgotten)",
            "Data breach notification within 72 hours",
            "Privacy policy in clear language",
            "Cookie consent banner",
            "Data Processing Agreement with vendors",
        ],
        "penalty": "Up to 4% of global revenue or €20M",
    },
    "ccpa": {
        "region": "California, USA",
        "requirements": [
            "Right to know what data is collected",
            "Right to delete personal data",
            "Right to opt-out of data sale",
            "'Do Not Sell My Personal Information' link",
            "Updated privacy policy with CCPA disclosures",
        ],
        "threshold": "$25M revenue OR 50K+ consumers OR 50%+ revenue from data",
    },
    "coppa": {
        "region": "USA (children under 13)",
        "requirements": [
            "Verifiable parental consent before collecting data",
            "Clear privacy policy about data practices",
            "Parents can review/delete child's data",
            "Data minimization",
        ],
        "penalty": "Up to $50,120 per violation",
    },
}


def check_privacy(
    sells_to_eu: bool = False,
    sells_to_children: bool = False,
) -> dict[str, Any]:
    """Check privacy compliance requirements."""
    applicable = ["ccpa"]
    requirements = list(PRIVACY_REGULATIONS["ccpa"]["requirements"])

    if sells_to_eu:
        applicable.append("gdpr")
        requirements.extend(PRIVACY_REGULATIONS["gdpr"]["requirements"])

    if sells_to_children:
        applicable.append("coppa")
        requirements.extend(PRIVACY_REGULATIONS["coppa"]["requirements"])

    return {
        "applicable_regulations": applicable,
        "requirements": requirements,
        "penalties": {
            reg: PRIVACY_REGULATIONS[reg].get("penalty", PRIVACY_REGULATIONS[reg].get("threshold", "varies"))
            for reg in applicable
        },
    }
