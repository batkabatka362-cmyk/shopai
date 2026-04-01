"""
rules.py — Regulatory requirements, certification rules, and labeling rules.

Each category maps to the agencies that regulate it, what certifications
are mandatory vs. recommended, and what labeling is legally required.
"""

# ---------------------------------------------------------------------------
# Agency requirements keyed by product category
# ---------------------------------------------------------------------------
REGULATORY_REQUIREMENTS = {
    "supplements": {
        "agencies": ["FDA"],
        "mandatory": ["gmp_compliance", "ndi_notification", "label_claims_review"],
        "recommended": ["third_party_testing", "nsf_certification"],
        "banned_ingredients_list": True,
        "import_restricted": False,
    },
    "cosmetics": {
        "agencies": ["FDA"],
        "mandatory": ["ingredient_review", "label_compliance", "mocra_registration"],
        "recommended": ["stability_testing", "challenge_testing"],
        "banned_ingredients_list": True,
        "import_restricted": False,
    },
    "food": {
        "agencies": ["FDA", "USDA"],
        "mandatory": ["facility_registration", "haccp_plan", "nutrition_label"],
        "recommended": ["organic_certification", "non_gmo_verification"],
        "banned_ingredients_list": True,
        "import_restricted": True,
    },
    "children_products": {
        "agencies": ["CPSC"],
        "mandatory": ["cpsia_testing", "cpc_certificate", "tracking_label"],
        "recommended": ["astm_voluntary_standards"],
        "banned_ingredients_list": False,
        "import_restricted": False,
    },
    "electronics": {
        "agencies": ["FCC"],
        "mandatory": ["fcc_certification", "ul_listing"],
        "recommended": ["energy_star", "rohs_compliance"],
        "banned_ingredients_list": False,
        "import_restricted": False,
    },
    "toys": {
        "agencies": ["CPSC", "FCC"],
        "mandatory": ["cpsia_testing", "cpc_certificate", "astm_f963", "tracking_label"],
        "recommended": ["voluntary_recall_plan"],
        "banned_ingredients_list": False,
        "import_restricted": False,
    },
    "general": {
        "agencies": [],
        "mandatory": ["country_of_origin_label"],
        "recommended": ["liability_insurance"],
        "banned_ingredients_list": False,
        "import_restricted": False,
    },
}

# ---------------------------------------------------------------------------
# Certification requirements detail
# ---------------------------------------------------------------------------
CERTIFICATION_REQUIREMENTS = {
    "cpsia_testing": {
        "description": "Lead and phthalate testing for children's products",
        "max_lead_ppm": 100,
        "max_phthalate_ppm": 1000,
        "applies_to_age": 12,
        "third_party_lab_required": True,
    },
    "fcc_certification": {
        "description": "Electromagnetic emissions testing for electronics",
        "types": ["intentional_radiator", "unintentional_radiator", "incidental"],
        "requires_test_report": True,
        "fcc_id_required": True,
    },
    "cpc_certificate": {
        "description": "Children's Product Certificate required for all children's products",
        "must_cite_tests": True,
        "must_list_importer": True,
        "must_include_contact": True,
    },
    "gmp_compliance": {
        "description": "Good Manufacturing Practice for dietary supplements",
        "facility_audit_required": True,
        "record_keeping_years": 3,
    },
    "mocra_registration": {
        "description": "Modernization of Cosmetics Regulation Act facility registration",
        "annual_renewal": True,
        "adverse_event_reporting": True,
    },
}

# ---------------------------------------------------------------------------
# Labeling rules per category
# ---------------------------------------------------------------------------
LABELING_RULES = {
    "supplements": [
        "supplement_facts_panel", "ingredient_list", "allergen_statement",
        "net_quantity", "manufacturer_address", "disclaimer_statement",
    ],
    "cosmetics": [
        "ingredient_list_inci", "net_contents", "warnings",
        "manufacturer_info", "directions_for_use",
    ],
    "food": [
        "nutrition_facts", "ingredient_list", "allergen_declaration",
        "net_weight", "manufacturer_address", "country_of_origin",
    ],
    "children_products": [
        "tracking_label", "age_grading", "choking_hazard_warning",
        "importer_info", "country_of_origin",
    ],
    "electronics": [
        "fcc_id_label", "country_of_origin", "voltage_rating",
        "manufacturer_info", "safety_warnings",
    ],
    "general": [
        "country_of_origin",
    ],
}


def get_rules_for_category(category):
    """Return the full rule set for a given product category.

    Falls back to 'general' if the category is unknown.
    """
    cat = category.lower() if category else "general"
    reqs = REGULATORY_REQUIREMENTS.get(cat, REGULATORY_REQUIREMENTS["general"])
    labels = LABELING_RULES.get(cat, LABELING_RULES["general"])
    return {
        "regulatory": reqs,
        "labeling": labels,
        "category_resolved": cat if cat in REGULATORY_REQUIREMENTS else "general",
    }
