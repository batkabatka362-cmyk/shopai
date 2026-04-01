"""Market size estimation — TAM, SAM, SOM calculation.

TAM = Total Addressable Market (бүх зах зээл)
SAM = Serviceable Addressable Market (хүрч чадах хэсэг)
SOM = Serviceable Obtainable Market (бодитоор авч чадах хэсэг)

E-commerce-д:
  TAM = Category-ийн нийт online борлуулалт (жилд)
  SAM = TAM × geographic_reach × price_range_fit
  SOM = SAM × realistic_market_share (шинэ store = 0.1-1%)
"""
from __future__ import annotations

from typing import Any


# US e-commerce category sizes (annual, estimated, USD)
CATEGORY_TAM = {
    "electronics": 250_000_000_000,
    "clothing": 180_000_000_000,
    "home_garden": 120_000_000_000,
    "health_beauty": 95_000_000_000,
    "sports_outdoors": 65_000_000_000,
    "toys_games": 45_000_000_000,
    "pet_supplies": 35_000_000_000,
    "office_supplies": 28_000_000_000,
    "automotive": 55_000_000_000,
    "food_beverage": 40_000_000_000,
    "baby": 25_000_000_000,
    "jewelry": 30_000_000_000,
    "books": 20_000_000_000,
    "arts_crafts": 15_000_000_000,
}

# Shopify's share of US e-commerce (~10%)
SHOPIFY_MARKET_SHARE = 0.10

# New store realistic capture rates
CAPTURE_RATES = {
    "new_store": {"min": 0.0001, "max": 0.001, "typical": 0.0005},
    "established_1yr": {"min": 0.001, "max": 0.005, "typical": 0.002},
    "established_3yr": {"min": 0.005, "max": 0.02, "typical": 0.01},
    "market_leader": {"min": 0.02, "max": 0.10, "typical": 0.05},
}


def estimate_tam(category: str, sub_niche_pct: float = 1.0) -> dict[str, Any]:
    """Estimate Total Addressable Market for a category.

    Args:
        category: Product category name
        sub_niche_pct: What % of the category is this specific niche (0-1)
    """
    category_key = _normalize_category(category)
    base_tam = CATEGORY_TAM.get(category_key, 10_000_000_000)  # Default $10B

    tam = base_tam * max(0.01, min(1.0, sub_niche_pct))

    return {
        "category": category,
        "matched_category": category_key,
        "annual_tam_usd": round(tam),
        "monthly_tam_usd": round(tam / 12),
        "sub_niche_pct": sub_niche_pct,
        "source": "US e-commerce estimates",
    }


def estimate_sam(
    tam: float,
    geographic_reach: float = 1.0,
    price_range_fit: float = 0.5,
    platform_share: float = SHOPIFY_MARKET_SHARE,
) -> dict[str, Any]:
    """Estimate Serviceable Addressable Market.

    Args:
        tam: Total addressable market (annual USD)
        geographic_reach: What % of geography you serve (0-1)
        price_range_fit: What % of market your price range covers (0-1)
        platform_share: Shopify's share of e-commerce
    """
    sam = tam * geographic_reach * price_range_fit * platform_share

    return {
        "annual_sam_usd": round(sam),
        "monthly_sam_usd": round(sam / 12),
        "geographic_reach": geographic_reach,
        "price_range_fit": price_range_fit,
        "platform_share": platform_share,
    }


def estimate_som(
    sam: float,
    store_maturity: str = "new_store",
    competitive_advantage: float = 1.0,
) -> dict[str, Any]:
    """Estimate Serviceable Obtainable Market — what you can realistically capture.

    Args:
        sam: Serviceable addressable market (annual USD)
        store_maturity: new_store | established_1yr | established_3yr | market_leader
        competitive_advantage: Multiplier (1.0 = average, 2.0 = strong differentiation)
    """
    rates = CAPTURE_RATES.get(store_maturity, CAPTURE_RATES["new_store"])
    base_rate = rates["typical"]
    adjusted_rate = min(rates["max"] * 2, base_rate * competitive_advantage)

    som = sam * adjusted_rate
    som_range = {
        "min": round(sam * rates["min"] * competitive_advantage),
        "max": round(sam * rates["max"] * competitive_advantage),
        "typical": round(som),
    }

    return {
        "annual_som_usd": som_range,
        "monthly_som_usd": {
            "min": round(som_range["min"] / 12),
            "max": round(som_range["max"] / 12),
            "typical": round(som_range["typical"] / 12),
        },
        "capture_rate": round(adjusted_rate * 100, 4),
        "store_maturity": store_maturity,
        "competitive_advantage": competitive_advantage,
    }


def full_market_size(
    category: str,
    sub_niche_pct: float = 0.1,
    geographic_reach: float = 1.0,
    price_range_fit: float = 0.5,
    store_maturity: str = "new_store",
    competitive_advantage: float = 1.0,
) -> dict[str, Any]:
    """Complete TAM → SAM → SOM pipeline."""
    tam_result = estimate_tam(category, sub_niche_pct)
    tam = tam_result["annual_tam_usd"]

    sam_result = estimate_sam(tam, geographic_reach, price_range_fit)
    sam = sam_result["annual_sam_usd"]

    som_result = estimate_som(sam, store_maturity, competitive_advantage)

    return {
        "tam": tam_result,
        "sam": sam_result,
        "som": som_result,
        "summary": {
            "tam_annual": f"${tam:,}",
            "sam_annual": f"${sam:,}",
            "som_monthly_typical": f"${som_result['monthly_som_usd']['typical']:,}",
            "interpretation": _interpret(som_result["monthly_som_usd"]["typical"]),
        },
    }


def _normalize_category(category: str) -> str:
    """Map free-text category to known category key."""
    cat = category.lower().replace(" ", "_").replace("&", "_").replace("-", "_")
    if cat in CATEGORY_TAM:
        return cat
    # Fuzzy match
    for key in CATEGORY_TAM:
        if key in cat or cat in key:
            return key
    # Keyword match
    keyword_map = {
        "phone": "electronics", "laptop": "electronics", "gadget": "electronics",
        "shirt": "clothing", "dress": "clothing", "shoes": "clothing", "fashion": "clothing",
        "furniture": "home_garden", "decor": "home_garden", "kitchen": "home_garden",
        "vitamin": "health_beauty", "skincare": "health_beauty", "supplement": "health_beauty",
        "fitness": "sports_outdoors", "yoga": "sports_outdoors", "camping": "sports_outdoors",
        "dog": "pet_supplies", "cat": "pet_supplies", "pet": "pet_supplies",
        "toy": "toys_games", "game": "toys_games", "puzzle": "toys_games",
        "baby": "baby", "infant": "baby", "nursery": "baby",
        "necklace": "jewelry", "ring": "jewelry", "bracelet": "jewelry",
    }
    for keyword, mapped in keyword_map.items():
        if keyword in cat:
            return mapped
    return "health_beauty"  # Default to mid-size category


def _interpret(monthly_som: float) -> str:
    """Human-readable interpretation of SOM."""
    if monthly_som > 100000:
        return "Large opportunity — significant revenue potential"
    if monthly_som > 30000:
        return "Good opportunity — solid revenue potential for a focused store"
    if monthly_som > 10000:
        return "Moderate opportunity — viable but requires efficient operations"
    if monthly_som > 3000:
        return "Small niche — possible but margins must be high"
    return "Very small niche — consider broader positioning"
