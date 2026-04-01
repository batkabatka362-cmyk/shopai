"""LegalCompliance — real-time compliance checking for e-commerce operations.

What veterans know:
  - FDA: supplements, cosmetics, food need specific compliance
  - FTC: advertising claims must be truthful, testimonials need disclaimers
  - CPSC: children's products need certification
  - GDPR/CCPA: customer data collection needs consent
  - ADA/WCAG: website accessibility requirements
  - Advertising: "results not typical" disclaimers, no false scarcity

This module checks products, ads, and actions for compliance BEFORE execution.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

logger = get_logger("intelligence.compliance")


# Product categories that require specific compliance
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

# FTC advertising rules
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

# Prohibited advertising claims
PROHIBITED_CLAIMS = [
    "cure", "treat", "prevent", "diagnose",  # Drug claims for non-drugs
    "guaranteed results", "100% effective",    # Unsubstantiated
    "FDA approved" ,                           # Unless actually FDA approved
    "clinically proven",                       # Without actual clinical trials
    "risk-free",                               # No investment is risk-free
    "miracle",                                 # Hyperbolic
]

# Privacy requirements by regulation
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


class LegalCompliance:
    """Real-time compliance checking for e-commerce operations.

    Usage:
        compliance = LegalCompliance()
        result = compliance.check_product({"title": "Vitamin C", "category": "supplements"})
        result = compliance.check_advertising("Buy now! Clinically proven to cure headaches!")
        result = compliance.full_audit(products, ads)
    """

    def full_audit(
        self,
        products: list[dict[str, Any]] | None = None,
        ad_content: list[str] | None = None,
        collects_data: bool = True,
        sells_to_children: bool = False,
        sells_to_eu: bool = False,
    ) -> dict[str, Any]:
        """Run full compliance audit."""
        result: dict[str, Any] = {"violations": [], "warnings": [], "compliant_areas": []}

        # Product compliance
        if products:
            product_results = [self.check_product(p) for p in products]
            violations = [r for r in product_results if not r["compliant"]]
            result["product_compliance"] = {
                "total_checked": len(product_results),
                "compliant": len(product_results) - len(violations),
                "non_compliant": len(violations),
                "details": product_results,
            }
            for v in violations:
                result["violations"].extend(v.get("violations", []))

        # Advertising compliance
        if ad_content:
            ad_results = [self.check_advertising(ad) for ad in ad_content]
            ad_violations = [r for r in ad_results if not r["compliant"]]
            result["advertising_compliance"] = {
                "total_checked": len(ad_results),
                "compliant": len(ad_results) - len(ad_violations),
                "non_compliant": len(ad_violations),
                "details": ad_results,
            }
            for v in ad_violations:
                result["violations"].extend(v.get("violations", []))

        # Privacy compliance
        if collects_data:
            privacy = self.check_privacy(sells_to_eu=sells_to_eu, sells_to_children=sells_to_children)
            result["privacy_compliance"] = privacy
            result["warnings"].extend(privacy.get("requirements", []))

        # Summary
        result["overall_compliant"] = len(result["violations"]) == 0
        result["violation_count"] = len(result["violations"])
        result["warning_count"] = len(result["warnings"])
        result["risk_level"] = (
            "critical" if len(result["violations"]) > 3
            else "high" if len(result["violations"]) > 0
            else "medium" if len(result["warnings"]) > 3
            else "low"
        )

        return result

    def check_product(self, product: dict[str, Any]) -> dict[str, Any]:
        """Check a product for category-specific compliance requirements."""
        category = self._detect_category(product)
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

        # Check for common violations
        title = (product.get("title", "") + " " + product.get("description", "")).lower()

        if category in ("supplements", "cosmetics", "food"):
            for claim in PROHIBITED_CLAIMS[:4]:  # Drug claims
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

    def check_advertising(self, content: str) -> dict[str, Any]:
        """Check advertising content for FTC compliance."""
        content_lower = content.lower()
        violations = []
        warnings = []

        # Check prohibited claims
        for claim in PROHIBITED_CLAIMS:
            if claim in content_lower:
                violations.append(f"Prohibited claim detected: '{claim}'")

        # Check for scarcity claims
        scarcity_words = ["limited time", "only x left", "selling fast", "almost gone", "last chance"]
        for word in scarcity_words:
            if word in content_lower:
                warnings.append(f"Scarcity claim '{word}' — must be truthful per FTC guidelines")

        # Check for endorsement disclosure
        endorsement_words = ["influencer", "sponsored", "partner", "ambassador"]
        has_endorsement = any(w in content_lower for w in endorsement_words)
        has_disclosure = "#ad" in content_lower or "#sponsored" in content_lower or "paid partnership" in content_lower
        if has_endorsement and not has_disclosure:
            violations.append("Endorsement detected without required FTC disclosure (#ad/#sponsored)")

        # Check for price comparison
        if "was $" in content_lower or "originally $" in content_lower or "save $" in content_lower:
            warnings.append("Price comparison — ensure former price was genuine and recent")

        return {
            "content_preview": content[:100] + ("..." if len(content) > 100 else ""),
            "compliant": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "ftc_rules_reference": list(FTC_ADVERTISING_RULES.keys()),
        }

    def check_privacy(
        self,
        sells_to_eu: bool = False,
        sells_to_children: bool = False,
    ) -> dict[str, Any]:
        """Check privacy compliance requirements."""
        applicable = ["ccpa"]  # CCPA applies to most US online businesses
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

    def _detect_category(self, product: dict[str, Any]) -> str | None:
        """Detect regulated category from product data."""
        category = (product.get("product_type", "") + " " + product.get("category", "")).lower()
        title = (product.get("title", "") + " " + product.get("name", "")).lower()
        tags = " ".join(product.get("tags", [])).lower() if isinstance(product.get("tags"), list) else ""
        combined = f"{category} {title} {tags}"

        category_keywords = {
            "supplements": ["supplement", "vitamin", "mineral", "protein", "probiotic", "herbal", "dietary"],
            "cosmetics": ["cosmetic", "skincare", "makeup", "beauty", "cream", "serum", "moisturizer", "sunscreen"],
            "food": ["food", "snack", "candy", "beverage", "drink", "tea", "coffee", "organic food"],
            "electronics": ["electronic", "charger", "cable", "bluetooth", "wireless", "speaker", "headphone"],
            "children": ["kids", "children", "baby", "infant", "toddler", "toy", "nursery"],
            "textiles": ["clothing", "apparel", "shirt", "dress", "fabric", "cotton", "textile"],
        }

        for cat, keywords in category_keywords.items():
            if any(kw in combined for kw in keywords):
                return cat

        return None
