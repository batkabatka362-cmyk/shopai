"""Blacklist rules — categories, keywords, and platform restrictions.

Defines what is blocked, restricted, or flagged for caution across
selling platforms. Severity levels:
  blocked    — cannot sell, will result in account termination
  restricted — requires approval, license, or special conditions
  caution    — technically allowed but risky, proceed carefully
"""
from __future__ import annotations

from typing import Any


# Categories that are universally blocked on most platforms
BLOCKED_CATEGORIES = {
    "weapons": {
        "severity": "blocked",
        "keywords": ["firearm", "gun", "ammunition", "ammo", "explosive",
                      "switchblade", "brass knuckles", "silencer", "suppressor"],
        "reason": "Weapons and ammunition are prohibited on all major platforms",
    },
    "drugs": {
        "severity": "blocked",
        "keywords": ["cocaine", "heroin", "methamphetamine", "fentanyl",
                      "drug paraphernalia", "bong", "crack pipe", "rolling papers"],
        "reason": "Controlled substances and drug paraphernalia are illegal to sell",
    },
    "counterfeit": {
        "severity": "blocked",
        "keywords": ["replica", "knockoff", "fake designer", "counterfeit",
                      "imitation brand", "AAA quality replica"],
        "reason": "Counterfeit goods result in immediate account termination and legal action",
    },
    "adult": {
        "severity": "blocked",
        "keywords": ["explicit", "pornographic", "sex toy", "adult novelty",
                      "xxx", "erotic"],
        "reason": "Adult content is restricted on most mainstream platforms",
    },
    "endangered_species": {
        "severity": "blocked",
        "keywords": ["ivory", "tortoiseshell", "exotic animal parts",
                      "shark fin", "pangolin", "rhino horn"],
        "reason": "CITES-protected species products are internationally banned",
    },
    "explosives": {
        "severity": "blocked",
        "keywords": ["dynamite", "c4", "detonator", "blasting cap",
                      "fireworks bulk", "black powder"],
        "reason": "Explosive materials require ATF licensing and are platform-banned",
    },
}

# Categories that need approval or licensing
RESTRICTED_CATEGORIES = {
    "tobacco": {
        "severity": "restricted",
        "keywords": ["cigarette", "cigar", "vape", "e-cigarette", "nicotine",
                      "tobacco", "hookah", "rolling tobacco"],
        "reason": "Tobacco and nicotine products require age verification and licensing",
    },
    "alcohol": {
        "severity": "restricted",
        "keywords": ["wine", "beer", "spirits", "liquor", "whiskey",
                      "vodka", "rum", "tequila"],
        "reason": "Alcohol sales require state-specific licensing and age verification",
    },
    "gambling": {
        "severity": "restricted",
        "keywords": ["slot machine", "poker chips", "gambling device",
                      "lottery ticket", "betting"],
        "reason": "Gambling equipment is regulated by state and federal law",
    },
    "supplements": {
        "severity": "caution",
        "keywords": ["weight loss pill", "testosterone booster", "steroid alternative",
                      "fat burner", "muscle builder", "diet pill"],
        "reason": "Supplements with drug claims violate FDA regulations",
    },
    "cbd": {
        "severity": "restricted",
        "keywords": ["cbd", "cannabidiol", "hemp extract", "thc",
                      "cannabis", "marijuana"],
        "reason": "CBD legality varies by state; advertising restricted on most platforms",
    },
}

# Keywords that trigger trademark review
RESTRICTED_KEYWORDS = [
    "nike", "adidas", "gucci", "louis vuitton", "chanel", "rolex",
    "supreme", "yeezy", "jordan", "prada", "hermes", "burberry",
    "disney", "marvel", "pokemon", "nintendo", "apple", "samsung",
    "nfl", "nba", "mlb", "fifa", "olympic", "super bowl",
    "ray-ban", "oakley", "tiffany", "coach", "versace",
]

# Platform-specific restrictions beyond universal rules
PLATFORM_RESTRICTIONS = {
    "shopify": {
        "blocked_extras": ["multi-level marketing schemes", "get rich quick"],
        "restricted_extras": ["dropship with no quality control"],
        "ad_policy": "Shopify Payments may freeze funds for high-risk categories",
        "policy_url": "https://www.shopify.com/legal/aup",
    },
    "amazon": {
        "blocked_extras": ["used items sold as new", "product without UPC/EAN"],
        "restricted_extras": ["topicals", "pesticides", "laser products",
                              "dietary supplements", "jewelry over $300"],
        "ad_policy": "Amazon requires category approval for many restricted items",
        "policy_url": "https://sellercentral.amazon.com/gp/help/G200164330",
    },
    "facebook": {
        "blocked_extras": ["before/after photos", "personal health claims",
                           "surveillance equipment", "multilevel marketing"],
        "restricted_extras": ["weight loss products", "crypto", "financial services",
                              "dating services", "online pharmacy"],
        "ad_policy": "Facebook rejects ads with exaggerated claims or before/after images",
        "policy_url": "https://www.facebook.com/policies/ads/",
    },
    "google": {
        "blocked_extras": ["misleading claims", "fake documents", "hacking software"],
        "restricted_extras": ["healthcare", "financial products", "political ads",
                              "alcohol", "gambling"],
        "ad_policy": "Google Ads requires certification for restricted categories",
        "policy_url": "https://support.google.com/adspolicy/answer/6008942",
    },
    "tiktok": {
        "blocked_extras": ["weight loss claims", "financial advice products",
                           "political merchandise"],
        "restricted_extras": ["beauty products with health claims",
                              "supplements", "intimate apparel"],
        "ad_policy": "TikTok Shop has strict product listing requirements with photo review",
        "policy_url": "https://seller.tiktok.com/university/policy",
    },
}


def get_rules_for_platform(platform: str) -> dict[str, Any]:
    """Return combined blocked + restricted rules for a specific platform."""
    base_rules = {
        "blocked": dict(BLOCKED_CATEGORIES),
        "restricted": dict(RESTRICTED_CATEGORIES),
        "trademark_keywords": list(RESTRICTED_KEYWORDS),
    }
    platform_key = platform.lower().strip()
    if platform_key in PLATFORM_RESTRICTIONS:
        extras = PLATFORM_RESTRICTIONS[platform_key]
        base_rules["platform_blocked_extras"] = extras.get("blocked_extras", [])
        base_rules["platform_restricted_extras"] = extras.get("restricted_extras", [])
        base_rules["ad_policy_note"] = extras.get("ad_policy", "")
        base_rules["policy_url"] = extras.get("policy_url", "")
    return base_rules
