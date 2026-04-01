"""Expert compliance knowledge for product sellers.

Hard-won insights from e-commerce compliance, common mistakes,
and practical guidance for staying on the right side of platform
policies and regulations.
"""
from __future__ import annotations

from typing import Any


# Core compliance knowledge organized by topic
COMPLIANCE_KNOWLEDGE = {
    "supplements": {
        "key_rule": "Supplements need the FDA disclaimer. Cannot claim to treat, cure, or prevent disease.",
        "details": [
            "Structure/function claims OK (e.g., 'supports immune health')",
            "Disease claims illegal without FDA drug approval",
            "GMP compliance (21 CFR Part 111) required for manufacturing",
        ],
        "common_violations": [
            "Before/after photos implying medical results",
            "Claiming supplement replaces prescription medication",
            "Missing FDA disclaimer on product listings",
        ],
    },
    "cosmetics": {
        "key_rule": "Cosmetics claiming to alter body structure/function = drugs by FDA. Need drug approval.",
        "details": [
            "'Makes skin look younger' = cosmetic (OK). 'Reduces wrinkles 50%' = drug (NOT OK)",
            "EU bans 1,300+ ingredients vs FDA's ~30",
            "Cosmetics do NOT need FDA pre-market approval but must be safe",
        ],
        "common_violations": [
            "Drug claims in descriptions or ads",
            "Claiming products are 'FDA approved' (cosmetics are never FDA approved)",
        ],
    },
    "counterfeit": {
        "key_rule": "Counterfeit goods = immediate account termination, legal action, criminal prosecution.",
        "details": [
            "'Inspired by' products can still trigger IP complaints",
            "Brand names in SEO keywords = trademark infringement",
            "Customs can seize counterfeit imports at the border",
        ],
        "common_violations": [
            "Listing 'Nike style' or 'Gucci inspired' products",
            "Dropshipping products that arrive with fake brand logos",
        ],
    },
    "platform_policies": {
        "key_rule": "Each platform has its own restrictions on top of legal requirements.",
        "details": [
            "Shopify Payments restricts high-risk categories",
            "Amazon requires category approval for 20+ restricted categories",
            "Facebook Ads rejects before/after imagery and bold health claims",
        ],
        "common_violations": [
            "Running Facebook ads for supplements without disclaimers",
            "Using Shopify Payments for CBD or adult products",
        ],
    },
    "international_selling": {
        "key_rule": "Must comply with BOTH origin and destination country regulations.",
        "details": [
            "EU CE marking required for electronics, toys, medical devices",
            "Canada requires bilingual (EN/FR) labels",
            "California Prop 65 warnings for products with listed chemicals",
        ],
        "common_violations": [
            "Shipping electronics to EU without CE marking",
            "Ignoring Prop 65 for California customers",
        ],
    },
}

# Common mistakes new sellers make that lead to account issues
COMMON_SELLER_MISTAKES = [
    {
        "mistake": "Assuming legal in my country means legal everywhere",
        "consequence": "Customs seizure, platform suspension, legal liability",
        "fix": "Research destination country regulations before listing",
    },
    {
        "mistake": "Using brand names in product titles for SEO",
        "consequence": "IP complaint, listing removal, possible account suspension",
        "fix": "Describe the product by features, not by brand comparison",
    },
    {
        "mistake": "Dropshipping without inspecting actual product received",
        "consequence": "Customers receive counterfeit or unsafe goods, chargebacks",
        "fix": "Order samples from every supplier before listing products",
    },
    {
        "mistake": "Making health claims on supplement or cosmetic listings",
        "consequence": "FDA warning letter, FTC fine, platform ad rejection",
        "fix": "Use only structure/function claims with required disclaimers",
    },
    {
        "mistake": "Selling CBD assuming it is legal because it is derived from hemp",
        "consequence": "Payment processor freeze, platform ban, state-level fines",
        "fix": "Verify CBD legality in every state you ship to and use compliant processors",
    },
    {
        "mistake": "Ignoring product safety testing for children's products",
        "consequence": "CPSC enforcement, massive liability if child is harmed",
        "fix": "Get CPSIA testing from CPSC-accepted lab before selling any kids' product",
    },
    {
        "mistake": "Relabeling products without proper compliance",
        "consequence": "Mislabeling violations, recalls, customer harm",
        "fix": "Work with a compliance consultant when private labeling regulated products",
    },
]

# How to verify product legality — step-by-step guide
LEGALITY_VERIFICATION_STEPS = [
    "1. Check if the product category is universally banned (weapons, drugs, counterfeit)",
    "2. Search CPSC recall database for the specific product or similar products",
    "3. Verify no trademark or IP infringement in product name, design, or packaging",
    "4. Check FDA status if product is supplement, cosmetic, food, or medical device",
    "5. Review target platform's restricted products policy",
    "6. Check destination country requirements (CE, UKCA, TGA, etc.)",
    "7. Verify shipping carrier restrictions (hazmat, lithium batteries, liquids)",
    "8. Consult a trade compliance attorney for high-value or high-risk products",
]


def diagnose_violation(violation_type: str) -> dict[str, Any]:
    """Return expert knowledge about a specific violation type."""
    vtype = violation_type.lower().strip()
    for topic, knowledge in COMPLIANCE_KNOWLEDGE.items():
        if vtype in topic or topic in vtype:
            return {
                "topic": topic,
                "key_rule": knowledge["key_rule"],
                "details": knowledge["details"],
                "common_violations": knowledge["common_violations"],
            }
    return {
        "topic": vtype,
        "key_rule": "No specific expert knowledge found for this violation type",
        "details": [],
        "common_violations": [],
        "suggestion": "Consult platform policy documentation or a compliance professional",
    }


def get_common_mistakes(seller_type: str = "new") -> list[dict[str, Any]]:
    """Return common mistakes relevant to a seller type."""
    if seller_type == "new":
        return COMMON_SELLER_MISTAKES
    # Experienced sellers mostly face scaling and international issues
    return [m for m in COMMON_SELLER_MISTAKES
            if any(kw in m["mistake"].lower()
                   for kw in ("country", "brand", "dropship", "cbd", "relabel"))]
