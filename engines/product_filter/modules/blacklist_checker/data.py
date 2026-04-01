"""Blacklist data — substance lists, trademark terms, country restrictions.

Reference data for compliance checks. Sources:
  - FDA 21 CFR for supplements and cosmetics
  - EU Cosmetics Regulation (EC) No 1223/2009
  - US CPSC banned/recalled product lists
  - Platform Terms of Service (Shopify, Amazon, Facebook, TikTok)
"""
from __future__ import annotations

from typing import Any


# Restricted product categories with detail descriptions
RESTRICTED_CATEGORIES = {
    "weapons_firearms": {
        "description": "All firearms, parts, ammunition, and accessories",
        "legal_reference": "18 U.S.C. 922 — Federal firearms law",
        "exceptions": ["airsoft guns (some platforms)", "paintball markers"],
    },
    "controlled_substances": {
        "description": "Schedule I-V drugs, precursors, and paraphernalia",
        "legal_reference": "21 U.S.C. 841 — Controlled Substances Act",
        "exceptions": ["FDA-approved OTC medications with proper licensing"],
    },
    "hazardous_materials": {
        "description": "Flammable, corrosive, toxic, or radioactive materials",
        "legal_reference": "49 CFR — DOT hazmat shipping regulations",
        "exceptions": ["consumer quantities of household chemicals"],
    },
    "recalled_products": {
        "description": "Products recalled by CPSC, FDA, or manufacturer",
        "legal_reference": "Consumer Product Safety Act",
        "exceptions": [],
    },
    "counterfeit_goods": {
        "description": "Unauthorized use of trademarks, logos, or brand identities",
        "legal_reference": "18 U.S.C. 2320 — Trafficking in counterfeit goods",
        "exceptions": ["authorized resellers with documentation"],
    },
}

# Banned substances by product type — simplified from FDA and EU regulations
BANNED_SUBSTANCES = {
    "cosmetics": {
        "source": "EU Cosmetics Regulation Annex II + FDA 21 CFR 700",
        "banned": [
            "mercury", "lead acetate", "chloroform", "methylene chloride",
            "bithionol", "hexachlorophene", "vinyl chloride",
            "zirconium in aerosol", "halogenated salicylanilides",
            "formaldehyde (above 0.2%)", "hydroquinone (above 2% OTC)",
        ],
        "requires_disclosure": [
            "parabens", "sulfates", "phthalates", "triclosan",
            "oxybenzone", "retinol (in high concentrations)",
        ],
    },
    "supplements": {
        "source": "FDA DSHEA 1994 + FTC advertising guidelines",
        "banned": [
            "ephedra (ephedrine alkaloids)", "androstenedione",
            "dimethylamylamine (DMAA)", "phenolphthalein",
            "sibutramine", "synthetic steroids", "kava (in some states)",
            "aristolochic acid", "comfrey (internal use)",
        ],
        "requires_disclaimer": (
            "These statements have not been evaluated by the FDA. "
            "This product is not intended to diagnose, treat, cure, "
            "or prevent any disease."
        ),
    },
    "children_products": {
        "source": "CPSIA 2008 + ASTM F963",
        "banned": [
            "lead (above 100 ppm)", "phthalates (above 0.1%)",
            "small parts (under 3 years)", "sharp edges",
            "toxic paints", "magnets (small, high-powered)",
            "button batteries (accessible)",
        ],
        "requires_testing": "Third-party CPSC-accepted lab testing required",
    },
    "food_contact": {
        "source": "FDA 21 CFR 174-186",
        "banned": [
            "BPA (in infant products)", "melamine",
            "lead glazes", "cadmium (above limits)",
        ],
        "requires_compliance": "FDA food contact notification or GRAS status",
    },
}

# Known trademark terms — brands that aggressively enforce IP
TRADEMARK_TERMS = {
    "luxury_fashion": [
        "louis vuitton", "gucci", "chanel", "hermes", "prada",
        "burberry", "versace", "dior", "balenciaga", "fendi",
    ],
    "sportswear": [
        "nike", "adidas", "under armour", "jordan", "yeezy",
        "new balance", "puma", "reebok", "lululemon",
    ],
    "tech": [
        "apple", "samsung", "sony", "microsoft", "google",
        "airpods", "iphone", "macbook", "galaxy",
    ],
    "entertainment": [
        "disney", "marvel", "star wars", "pokemon", "nintendo",
        "harry potter", "dc comics", "pixar", "sesame street",
    ],
    "sports_leagues": [
        "nfl", "nba", "mlb", "nhl", "fifa", "ufc",
        "premier league", "olympic", "super bowl", "world cup",
    ],
}

# Country-specific restrictions for international sellers
COUNTRY_RESTRICTIONS = {
    "us": {
        "requires_fda": ["supplements", "cosmetics", "food", "medical devices"],
        "requires_fcc": ["electronics with radio/wifi"],
        "requires_cpsc": ["children's products", "consumer goods"],
        "prop_65": "California requires Prop 65 warnings for products with listed chemicals",
    },
    "eu": {
        "requires_ce": ["electronics", "toys", "machinery", "medical devices"],
        "gdpr": "Digital products must comply with GDPR for EU customers",
        "reach": "Chemicals in products must comply with EU REACH regulation",
        "cosmetics_notification": "Cosmetics must be notified via CPNP portal",
    },
    "uk": {
        "requires_ukca": ["electronics", "toys", "machinery"],
        "post_brexit": "Separate compliance from EU since Jan 2021",
        "cosmetics": "Must register with UK SCPN (post-Brexit equivalent of CPNP)",
    },
    "canada": {
        "requires_nsc": ["consumer chemicals", "cosmetics"],
        "bilingual": "Product labels must be in English and French",
        "cannabis": "Strictly regulated federally, different from US state laws",
    },
    "australia": {
        "requires_accc": ["consumer goods with safety standards"],
        "tga": "Therapeutic goods (supplements, skincare with claims) need TGA approval",
        "quarantine": "Strict biosecurity for plant/animal-derived products",
    },
}

# Platform policy reference URLs
PLATFORM_POLICY_LINKS = {
    "shopify_aup": "https://www.shopify.com/legal/aup",
    "shopify_payments_tos": "https://www.shopify.com/legal/terms-payments-us",
    "amazon_restricted": "https://sellercentral.amazon.com/gp/help/G200164330",
    "amazon_ip_policy": "https://sellercentral.amazon.com/gp/help/G201361070",
    "facebook_commerce": "https://www.facebook.com/policies/commerce",
    "facebook_ads": "https://www.facebook.com/policies/ads/",
    "tiktok_seller": "https://seller.tiktok.com/university/policy",
    "google_shopping": "https://support.google.com/merchants/answer/6149970",
    "fda_cosmetics": "https://www.fda.gov/cosmetics",
    "fda_supplements": "https://www.fda.gov/food/dietary-supplements",
    "cpsc_recalls": "https://www.cpsc.gov/Recalls",
}


def get_substances_for_category(category: str) -> dict[str, Any]:
    """Return banned/restricted substance info for a product category."""
    category_lower = category.lower().strip()
    # Direct match
    if category_lower in BANNED_SUBSTANCES:
        return BANNED_SUBSTANCES[category_lower]
    # Keyword match
    keyword_map = {
        "skincare": "cosmetics", "beauty": "cosmetics", "makeup": "cosmetics",
        "lotion": "cosmetics", "cream": "cosmetics", "serum": "cosmetics",
        "vitamin": "supplements", "protein": "supplements", "herbal": "supplements",
        "diet": "supplements", "probiotic": "supplements",
        "toy": "children_products", "baby": "children_products", "kids": "children_products",
        "kitchen": "food_contact", "cookware": "food_contact", "mug": "food_contact",
    }
    for keyword, mapped in keyword_map.items():
        if keyword in category_lower:
            return BANNED_SUBSTANCES[mapped]
    return {"source": "General", "banned": [], "note": "No specific substance restrictions found"}
