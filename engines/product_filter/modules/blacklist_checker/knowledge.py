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
        "key_rule": (
            "Supplements need the FDA disclaimer on all product pages and labels. "
            "You CANNOT claim a supplement treats, cures, or prevents any disease."
        ),
        "details": [
            "Structure/function claims are allowed (e.g., 'supports immune health')",
            "Disease claims are illegal without FDA drug approval (e.g., 'cures cancer')",
            "The required disclaimer must appear near any health claim",
            "GMP compliance (21 CFR Part 111) is required for manufacturing",
            "Adverse event reporting is mandatory under DSHEA",
        ],
        "common_violations": [
            "Using before/after photos implying medical results",
            "Claiming a supplement replaces prescription medication",
            "Importing supplements without verifying ingredient legality",
            "Failing to include the FDA disclaimer on product listings",
        ],
    },
    "cosmetics": {
        "key_rule": (
            "Cosmetics that claim to alter body structure or function are "
            "classified as drugs by the FDA and require full drug approval."
        ),
        "details": [
            "'Makes skin look younger' = cosmetic claim (OK)",
            "'Reduces wrinkles by 50%' = drug claim (NOT OK without approval)",
            "'Anti-aging' is borderline — context determines classification",
            "EU has stricter ingredient bans (1,300+ banned vs FDA's ~30)",
            "Cosmetics do not need FDA pre-market approval but must be safe",
        ],
        "common_violations": [
            "Making drug claims in product descriptions or ads",
            "Using EU-banned ingredients while selling to EU customers",
            "Not listing all ingredients on product labels",
            "Claiming products are 'FDA approved' (cosmetics are not approved by FDA)",
        ],
    },
    "counterfeit": {
        "key_rule": (
            "Selling counterfeit goods results in immediate account termination, "
            "legal action from brand owners, and potential criminal prosecution."
        ),
        "details": [
            "Even 'inspired by' products can trigger IP complaints if too similar",
            "Using brand names in SEO keywords or product titles is infringement",
            "Brand owners actively monitor platforms with automated tools",
            "First-time offenses on Amazon often result in permanent suspension",
            "Customs can seize counterfeit imports at the border",
        ],
        "common_violations": [
            "Listing 'Nike style' or 'Gucci inspired' products",
            "Using brand logos or trademarked patterns in product images",
            "Dropshipping unbranded products that arrive with fake logos",
            "Using brand names as hidden keywords for search optimization",
        ],
    },
    "platform_policies": {
        "key_rule": (
            "Each platform has its own restricted product policies on top of "
            "legal requirements. Violating either can result in account suspension."
        ),
        "details": [
            "Shopify Payments restricts high-risk categories (use alt payment processor)",
            "Amazon requires category approval for 20+ restricted categories",
            "Facebook Ads rejects products with before/after imagery or bold health claims",
            "Google Shopping requires structured data and policy compliance for approval",
            "TikTok Shop has the strictest listing review process of all platforms",
        ],
        "common_violations": [
            "Running Facebook ads for supplements without proper disclaimers",
            "Listing restricted products on Amazon without category approval",
            "Using Shopify Payments for CBD or adult products",
            "Advertising gambling-related products on Google",
        ],
    },
    "international_selling": {
        "key_rule": (
            "Selling internationally means complying with BOTH origin and "
            "destination country regulations. Ignorance is not a defense."
        ),
        "details": [
            "EU CE marking is required for electronics, toys, and medical devices",
            "Canada requires bilingual (EN/FR) product labeling",
            "Australia has strict biosecurity — plant/animal products need permits",
            "UK post-Brexit requires separate UKCA marking from EU CE",
            "California Prop 65 warnings needed for products with listed chemicals",
        ],
        "common_violations": [
            "Shipping electronics to EU without CE marking",
            "Selling supplements in Australia without TGA compliance",
            "Ignoring Prop 65 requirements for California customers",
            "Not providing GDPR-compliant privacy notices for EU data",
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
