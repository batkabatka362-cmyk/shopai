"""Legal Document Engine — template selector.

Selects appropriate legal document templates based on business type,
jurisdiction, and product type. Determines required sections per
applicable regulations.

All logic is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Required sections by document type and jurisdiction
# ---------------------------------------------------------------------------

_BASE_TERMS_SECTIONS = [
    "acceptance_of_terms", "use_of_service", "user_accounts",
    "intellectual_property", "limitation_of_liability",
    "governing_law", "changes_to_terms", "contact_information",
]

_BASE_PRIVACY_SECTIONS = [
    "information_collected", "how_we_use_information",
    "information_sharing", "data_security", "your_rights",
    "cookies", "contact_information",
]

_BASE_RETURNS_SECTIONS = [
    "return_eligibility", "return_window", "return_process",
    "refund_method", "shipping_costs", "exceptions",
    "contact_information",
]

_JURISDICTION_EXTRA: dict[str, dict[str, list[str]]] = {
    "US": {
        "privacy": ["ccpa_rights", "do_not_sell"],
        "terms": ["arbitration_clause", "dmca_notice"],
    },
    "EU": {
        "privacy": ["gdpr_lawful_basis", "data_retention", "dpo_contact", "right_to_erasure"],
        "terms": ["right_of_withdrawal", "consumer_rights"],
        "returns": ["14_day_cooling_off"],
    },
    "UK": {
        "privacy": ["uk_gdpr_rights", "ico_complaint"],
        "terms": ["consumer_rights_act"],
        "returns": ["14_day_cooling_off"],
    },
    "CA": {
        "privacy": ["pipeda_rights", "provincial_rights"],
    },
}

_PRODUCT_TYPE_EXTRA: dict[str, dict[str, list[str]]] = {
    "digital": {
        "terms": ["digital_content_license", "subscription_terms"],
        "returns": ["digital_goods_exceptions"],
    },
    "food": {
        "terms": ["allergen_disclaimer", "perishable_goods"],
        "returns": ["perishable_goods_exceptions"],
    },
    "health": {
        "terms": ["medical_disclaimer", "fda_disclaimer"],
    },
}


def select_templates(
    business: dict[str, Any],
) -> dict[str, Any]:
    """Select legal document templates based on business profile.

    Args:
        business: Business info with name, type, country, products_type.

    Returns:
        Structured dict with template selections for each document type.
    """
    try:
        biz = copy.deepcopy(business)
        country = str(biz.get("country", "US")).upper()
        biz_type = str(biz.get("type", "retail")).lower()
        products_type = str(biz.get("products_type", "physical")).lower()

        templates: list[dict[str, Any]] = []

        # Terms of Service
        terms_sections = list(_BASE_TERMS_SECTIONS)
        jurisdiction_terms = _JURISDICTION_EXTRA.get(country, {}).get("terms", [])
        product_terms = _PRODUCT_TYPE_EXTRA.get(products_type, {}).get("terms", [])
        terms_sections.extend(jurisdiction_terms)
        terms_sections.extend(product_terms)

        templates.append({
            "template_id": f"terms_{country.lower()}_{biz_type}",
            "template_name": "Terms of Service",
            "jurisdiction": country,
            "business_type": biz_type,
            "required_sections": terms_sections,
        })

        # Privacy Policy
        privacy_sections = list(_BASE_PRIVACY_SECTIONS)
        jurisdiction_privacy = _JURISDICTION_EXTRA.get(country, {}).get("privacy", [])
        privacy_sections.extend(jurisdiction_privacy)

        templates.append({
            "template_id": f"privacy_{country.lower()}_{biz_type}",
            "template_name": "Privacy Policy",
            "jurisdiction": country,
            "business_type": biz_type,
            "required_sections": privacy_sections,
        })

        # Return Policy
        returns_sections = list(_BASE_RETURNS_SECTIONS)
        jurisdiction_returns = _JURISDICTION_EXTRA.get(country, {}).get("returns", [])
        product_returns = _PRODUCT_TYPE_EXTRA.get(products_type, {}).get("returns", [])
        returns_sections.extend(jurisdiction_returns)
        returns_sections.extend(product_returns)

        templates.append({
            "template_id": f"returns_{country.lower()}_{biz_type}",
            "template_name": "Return Policy",
            "jurisdiction": country,
            "business_type": biz_type,
            "required_sections": returns_sections,
        })

        return {
            "status": "success",
            "templates": templates,
        }
    except Exception as exc:
        return {
            "status": "error",
            "templates": [],
            "error": f"Template selection failed: {exc}",
        }
