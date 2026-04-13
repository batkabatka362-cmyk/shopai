"""
data.py — Agency contacts, certification costs, processing times, required documents.

All dollar figures are USD estimates as of 2025.  Actual costs vary by
lab, product complexity, and expedite fees.
"""

# ---------------------------------------------------------------------------
# Agency contact information
# ---------------------------------------------------------------------------
AGENCY_CONTACTS = {
    "FDA": {
        "name": "Food and Drug Administration",
        "website": "https://www.fda.gov",
        "phone": "1-888-INFO-FDA",
        "submission_portal": "https://www.fda.gov/regulatory-information",
    },
    "CPSC": {
        "name": "Consumer Product Safety Commission",
        "website": "https://www.cpsc.gov",
        "phone": "1-800-638-2772",
        "recall_portal": "https://www.saferproducts.gov",
    },
    "FCC": {
        "name": "Federal Communications Commission",
        "website": "https://www.fcc.gov",
        "phone": "1-888-225-5322",
        "equipment_auth_portal": "https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm",
    },
    "USDA": {
        "name": "US Department of Agriculture",
        "website": "https://www.usda.gov",
        "phone": "1-202-720-2791",
        "organic_portal": "https://organic.ams.usda.gov",
    },
}

# ---------------------------------------------------------------------------
# Estimated certification costs (USD)
# ---------------------------------------------------------------------------
CERTIFICATION_COSTS = {
    "cpsia_testing": {"low": 500, "typical": 1500, "high": 4000},
    "cpc_certificate": {"low": 0, "typical": 0, "high": 0},  # free once tests done
    "fcc_certification": {"low": 5000, "typical": 10000, "high": 15000},
    "ul_listing": {"low": 5000, "typical": 15000, "high": 30000},
    "gmp_compliance": {"low": 2000, "typical": 5000, "high": 15000},
    "ndi_notification": {"low": 3000, "typical": 8000, "high": 20000},
    "third_party_testing": {"low": 1000, "typical": 3000, "high": 10000},
    "nsf_certification": {"low": 2000, "typical": 5000, "high": 12000},
    "mocra_registration": {"low": 0, "typical": 500, "high": 2000},
    "facility_registration": {"low": 0, "typical": 0, "high": 500},
    "haccp_plan": {"low": 1000, "typical": 3000, "high": 8000},
    "nutrition_label": {"low": 300, "typical": 800, "high": 2000},
    "organic_certification": {"low": 1000, "typical": 3000, "high": 7000},
    "astm_f963": {"low": 1000, "typical": 3000, "high": 6000},
    "rohs_compliance": {"low": 500, "typical": 1500, "high": 4000},
    "energy_star": {"low": 2000, "typical": 5000, "high": 10000},
    "label_claims_review": {"low": 500, "typical": 2000, "high": 5000},
    "ingredient_review": {"low": 200, "typical": 1000, "high": 3000},
    "stability_testing": {"low": 1000, "typical": 3000, "high": 8000},
}

# ---------------------------------------------------------------------------
# Processing times in business days
# ---------------------------------------------------------------------------
PROCESSING_TIMES = {
    "cpsia_testing": {"fast": 10, "typical": 21, "slow": 45},
    "fcc_certification": {"fast": 20, "typical": 45, "slow": 90},
    "ul_listing": {"fast": 30, "typical": 60, "slow": 120},
    "gmp_compliance": {"fast": 30, "typical": 60, "slow": 180},
    "ndi_notification": {"fast": 75, "typical": 90, "slow": 180},
    "third_party_testing": {"fast": 5, "typical": 14, "slow": 30},
    "mocra_registration": {"fast": 1, "typical": 5, "slow": 14},
    "haccp_plan": {"fast": 14, "typical": 30, "slow": 60},
    "nutrition_label": {"fast": 3, "typical": 7, "slow": 14},
    "organic_certification": {"fast": 30, "typical": 90, "slow": 180},
    "astm_f963": {"fast": 14, "typical": 30, "slow": 60},
    "label_claims_review": {"fast": 5, "typical": 14, "slow": 30},
}

# ---------------------------------------------------------------------------
# Required documents per product category
# ---------------------------------------------------------------------------
REQUIRED_DOCUMENTS = {
    "supplements": [
        "certificate_of_analysis", "gmp_audit_report", "ingredient_spec_sheets",
        "label_proof", "stability_data", "adverse_event_log",
    ],
    "cosmetics": [
        "ingredient_safety_assessments", "product_label_proof",
        "mocra_registration_confirmation", "challenge_test_results",
    ],
    "food": [
        "facility_registration_number", "haccp_plan_document",
        "nutrition_analysis_report", "allergen_control_plan",
        "supplier_verification_records",
    ],
    "children_products": [
        "cpsia_test_reports", "children_product_certificate",
        "tracking_label_specs", "age_determination_report",
    ],
    "electronics": [
        "fcc_test_report", "fcc_id_grant", "ul_certification",
        "product_schematic", "user_manual_with_safety_info",
    ],
    "toys": [
        "cpsia_test_reports", "astm_f963_test_report",
        "children_product_certificate", "age_grading_determination",
        "tracking_label_specs",
    ],
    "general": [
        "country_of_origin_documentation",
    ],
}


def get_documents_for_category(category):
    """Return the list of required documents for a product category."""
    cat = category.lower() if category else "general"
    return REQUIRED_DOCUMENTS.get(cat, REQUIRED_DOCUMENTS["general"])
