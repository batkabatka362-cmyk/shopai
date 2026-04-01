"""Marketplace trends expert knowledge."""
from __future__ import annotations
from typing import Any

MARKETPLACE_HEURISTICS = [
    "Amazon BSR #1000 in main category ≈ 10-30 sales/day — solid demand",
    "Products that stay in top 100 for 30+ days = sustained demand (not a fad)",
    "Look at 'Movers & Shakers' not just 'Best Sellers' — movers show MOMENTUM",
    "Amazon 'New Releases' + climbing BSR = validated new product opportunity",
    "Don't compete with Amazon Basics products — they'll undercut you every time",
    "Etsy trending = handmade/personalized angle viable at premium price",
    "If product has 10,000+ reviews on Amazon, market is mature — find the sub-niche",
    "Cross-marketplace trending (Amazon + Etsy + Shopify stores) = strongest signal",
    "Best adjacent products: accessories for bestsellers (cases, stands, refills)",
    "Bestseller with 3.5-star avg = quality gap opportunity — make it better",
]

ADJACENT_STRATEGY = {
    "accessories": {
        "description": "Sell accessories/add-ons for bestselling products",
        "examples": ["Phone case for popular phone", "Stand for popular tablet", "Replacement filters"],
        "advantage": "Proven demand, lower competition, repeat purchase potential",
        "margin": "Often higher margin than main product (40-60%)",
    },
    "premium_version": {
        "description": "Premium/improved version of commodity bestseller",
        "examples": ["Organic version of popular supplement", "Heavy-duty version of tool"],
        "advantage": "Customers searching for upgrade, willing to pay more",
        "margin": "20-40% above commodity price point",
    },
    "bundle": {
        "description": "Bundle bestseller with complementary products",
        "examples": ["Yoga mat + blocks + strap bundle", "Camera + case + SD card"],
        "advantage": "Higher AOV, harder to price-compare",
        "margin": "Bundle margin typically 35-50%",
    },
    "niche_variant": {
        "description": "Category-specific variant of general bestseller",
        "examples": ["Yoga mat for hot yoga (heat-resistant)", "Dog toy for aggressive chewers"],
        "advantage": "Less competition in specific niche, loyal customer base",
        "margin": "Can command 20-30% premium for specialization",
    },
}

def get_marketplace_heuristics() -> list[str]:
    return MARKETPLACE_HEURISTICS

def get_adjacent_product_strategy() -> dict[str, Any]:
    return ADJACENT_STRATEGY
